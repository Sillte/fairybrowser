import time
from contextlib import contextmanager
from dataclasses import FrozenInstanceError
from threading import Event, Thread, get_ident
from unittest.mock import MagicMock

import pytest
from playwright.sync_api import Page

from fairybrowser.devtools import (
    FetchTextStreamEvent,
    HTTPRequest,
    HTTPTransaction,
    ServerSentEvent,
    WebsocketConnection,
)
from fairybrowser.invocation import (
    FetchTextStreamEventListener,
    HTTPTransactionListener,
    InvocationConfiguration,
    InvocationContext,
    InvocationCreator,
    InvocationExecutor,
    ListenerEventException,
    ServerSentEventListener,
    TimerEvent,
    TimerEventListener,
    WebsocketConnectionListener,
)
from fairybrowser.models import BrowserInfo
from fairybrowser.shared.event import Disposable


def test_invocation_context_completion_sets_completion_event():
    context = InvocationContext()

    context.complete()

    assert context.completion_event.is_set()


def test_invocation_context_keeps_the_last_completed_listener_result():
    context = InvocationContext()

    assert context.listener_result is None

    assert context._begin_listener()
    context._finish_listener("first")
    assert context._begin_listener()
    context._finish_listener(None)

    assert context.listener_result is None


def test_invocation_context_waits_for_active_listeners_to_return():
    context = InvocationContext()
    assert context._begin_listener()
    finished = Event()
    waiter = Thread(target=lambda: (context._finish_listeners(), finished.set()))
    waiter.start()

    with context._listener_condition:
        while not context._listener_state.closed:
            context._listener_condition.wait()

    assert not finished.is_set()
    context._finish_listener("listener result")
    waiter.join(timeout=1)

    assert not waiter.is_alive()
    assert finished.is_set()
    assert context.listener_result == "listener result"


def test_invocation_context_timer_event_keeps_context_frozen():
    context = InvocationContext()
    event = TimerEvent(tick_count=1, scheduled_at=1.0, fired_at=1.1)

    context._set_timer_event(event)

    assert context.timer_event is event
    with pytest.raises(FrozenInstanceError):
        setattr(context, "timer_event", None)


def test_invocation_context_failure_sets_error_and_completion():
    context = InvocationContext()
    error = RuntimeError("listener failed")

    context.fail(error)

    assert context.error is error
    assert context.completion_event.is_set()


def test_invocation_context_failure_wraps_listener_event():
    context = InvocationContext()
    event = FetchTextStreamEvent(
        stream_id="fetch-1",
        event_type="error",
        url="https://example.com",
        method="GET",
        status=500,
        chunk_index=0,
        timestamp_ms=1.0,
        elapsed_ms=0.1,
        error="stream failed",
    )

    context.fail(event)

    assert isinstance(context.error, ListenerEventException)
    assert context.error.event is event
    assert context.completion_event.is_set()


@pytest.mark.parametrize("outcome", ["success", "start", "timeout"])
def test_invocation_executor_cleans_up(monkeypatch: pytest.MonkeyPatch, outcome: str):
    page = MagicMock(spec=Page)
    disposed: list[bool] = []
    services = []

    class FakeService:
        def __init__(self, **_kwargs):
            self.terminated = False
            services.append(self)

        def start(self):
            pass

        def terminate(self):
            self.terminated = True

    @contextmanager
    def fake_sync_page(**_kwargs):
        yield page

    monkeypatch.setattr("fairybrowser.invocation.models.sync_page", fake_sync_page)
    monkeypatch.setattr("fairybrowser.invocation.models.DevtoolsService", FakeService)

    def start(_input, _page, context):
        if outcome == "start":
            raise RuntimeError("start failed")
        if outcome == "success":
            context.complete()

    invocation = InvocationCreator.from_any(
        on_start=start,
        listeners=(),
    )
    executor = InvocationExecutor.from_any(invocation)
    monkeypatch.setattr(
        executor,
        "_subscribe",
        lambda *_args: [Disposable(lambda: disposed.append(True))],
    )

    if outcome == "success":
        assert executor.invoke(None, configuration=InvocationConfiguration(timeout=0)) is None
    else:
        with pytest.raises(RuntimeError if outcome == "start" else TimeoutError):
            executor.invoke(None, configuration=InvocationConfiguration(timeout=0))

    assert disposed == [True]
    assert services[0].terminated


def test_invocation_executor_propagates_listener_error_and_cleans_up(monkeypatch: pytest.MonkeyPatch):
    page = MagicMock(spec=Page)
    disposed: list[bool] = []
    services = []

    class FakeEvent:
        def subscribe(self, callback):
            self.callback = callback
            return Disposable(lambda: disposed.append(True))

    class FakeService:
        def __init__(self, **_kwargs):
            self.on_fetch_stream_event = FakeEvent()
            self.terminated = False
            services.append(self)

        def start(self):
            event = FetchTextStreamEvent(
                stream_id="fetch-1",
                event_type="chunk",
                url="https://example.com",
                method="GET",
                status=200,
                chunk_index=0,
                timestamp_ms=1.0,
                elapsed_ms=0.1,
                text="chunk",
            )
            self.on_fetch_stream_event.callback(event)

        def terminate(self):
            self.terminated = True

    @contextmanager
    def fake_sync_page(**_kwargs):
        yield page

    monkeypatch.setattr("fairybrowser.invocation.models.sync_page", fake_sync_page)
    monkeypatch.setattr("fairybrowser.invocation.models.DevtoolsService", FakeService)

    def failing_listener(_event):
        raise RuntimeError("listener failed")

    invocation = InvocationCreator.from_any(
        on_start=lambda _input, _page: None,
        on_completed=lambda _context: "unexpected",
        listeners=FetchTextStreamEventListener.from_any(failing_listener),
    )

    with pytest.raises(RuntimeError, match="listener failed"):
        InvocationExecutor.from_any(invocation).invoke(None)

    assert disposed == [True]
    assert services[0].terminated


def test_timer_listener_runs_on_page_thread_and_updates_context(monkeypatch: pytest.MonkeyPatch):
    page = MagicMock(spec=Page)
    page.wait_for_timeout.side_effect = lambda milliseconds: time.sleep(milliseconds / 1000)
    thread_id = get_ident()

    class FakeService:
        def __init__(self, **_kwargs):
            self.terminated = False

        def start(self):
            pass

        def terminate(self):
            self.terminated = True

    @contextmanager
    def fake_sync_page(**_kwargs):
        yield page

    monkeypatch.setattr("fairybrowser.invocation.models.sync_page", fake_sync_page)
    monkeypatch.setattr("fairybrowser.invocation.models.DevtoolsService", FakeService)
    received = []

    def on_timer(callback_page: Page, context: InvocationContext) -> str:
        received.append((callback_page, context.timer_event, get_ident()))
        context.complete()
        return "timer result"

    invocation = InvocationCreator.from_any(
        on_start=lambda _input, _page: None,
        listeners=[TimerEventListener(interval=0.01, listener=on_timer)],
    )

    result = InvocationExecutor.from_any(invocation).invoke(None, configuration=InvocationConfiguration(timeout=1))

    assert result == "timer result"
    assert received[0][0] is page
    assert received[0][1].tick_count == 1
    assert received[0][1].scheduled_at <= received[0][1].fired_at
    assert received[0][2] == thread_id


@pytest.mark.parametrize("interval", [0, -1, float("inf"), float("nan")])
def test_timer_listener_rejects_invalid_intervals(interval: float):
    with pytest.raises(ValueError, match="finite positive"):
        TimerEventListener(interval=interval, listener=lambda _page, _context: None)


@pytest.mark.parametrize(
    ("listener_type", "event"),
    [
        (
            HTTPTransactionListener,
            HTTPTransaction(request=HTTPRequest(url="https://example.com", method="GET")),
        ),
        (WebsocketConnectionListener, WebsocketConnection(request_id="ws-1", events=[])),
        (ServerSentEventListener, ServerSentEvent(request_id="sse-1", timestamp=1.0, data="event")),
        (
            FetchTextStreamEventListener,
            FetchTextStreamEvent(
                stream_id="fetch-1",
                event_type="chunk",
                url="https://example.com",
                method="GET",
                status=200,
                chunk_index=0,
                timestamp_ms=1.0,
                elapsed_ms=0.1,
                text="chunk",
            ),
        ),
    ],
)
def test_listeners_normalize_one_and_two_argument_handlers(listener_type, event):
    context = InvocationContext()
    received = []

    one_argument = listener_type.from_any(lambda item: received.append((item, None)))
    one_argument.listener(event, context)

    def two_arguments(item, received_context):
        received.append((item, received_context))

    with_context = listener_type.from_any(two_arguments)
    with_context.listener(event, context)

    assert received == [(event, None), (event, context)]


def test_invocation_configuration_from_any_defaults():
    configuration = InvocationConfiguration.from_any()

    assert configuration == InvocationConfiguration(timeout=120, browser_info=None)


def test_invocation_configuration_from_any_accepts_browser_info():
    browser_info = BrowserInfo(name="custom")

    configuration = InvocationConfiguration.from_any(browser_info)

    assert configuration == InvocationConfiguration(browser_info=browser_info)


def test_invocation_configuration_from_any_preserves_configuration():
    expected = InvocationConfiguration(timeout=30, browser_info=BrowserInfo(name="custom"))

    assert InvocationConfiguration.from_any(expected) is expected


def test_invocation_creator_from_any_accepts_single_typed_listener():
    received = []
    event = FetchTextStreamEvent(
        stream_id="fetch-1",
        event_type="chunk",
        url="https://example.com",
        method="GET",
        status=200,
        chunk_index=0,
        timestamp_ms=1.0,
        elapsed_ms=0.1,
        text="chunk",
    )
    creator = InvocationCreator.from_any(
        on_start=lambda _input, _page: None,
        on_completed=lambda _context: None,
        listeners=FetchTextStreamEventListener.from_any(lambda item: received.append(item)),
    )

    assert len(creator.listeners) == 1
    assert isinstance(creator.listeners[0], FetchTextStreamEventListener)
    creator.listeners[0].listener(event, InvocationContext())
    assert received == [event]


def test_invocation_creator_from_any_resolves_mixed_listener_sequence():
    http_listener = HTTPTransactionListener.from_any(lambda _transaction: None)
    fetch_listener = FetchTextStreamEventListener.from_any(lambda _event: None)

    creator = InvocationCreator.from_any(
        on_start=lambda _input, _page: None,
        on_completed=lambda _context: None,
        listeners=[http_listener, fetch_listener],
    )

    assert creator.listeners[0] is http_listener
    assert creator.listeners[1] is fetch_listener


def test_invocation_creator_resolves_raw_callables_from_event_annotations():
    def on_http(event: HTTPTransaction) -> None:
        pass

    def on_websocket(event: WebsocketConnection, _context: InvocationContext) -> None:
        pass

    def on_server_sent_event(event: ServerSentEvent) -> None:
        pass

    def on_fetch_stream(event: FetchTextStreamEvent) -> None:
        pass

    creator = InvocationCreator.from_any(
        on_start=lambda _input, _page: None,
        on_completed=lambda _context: None,
        listeners=[on_http, on_websocket, on_server_sent_event, on_fetch_stream],
    )

    assert [type(listener) for listener in creator.listeners] == [
        HTTPTransactionListener,
        WebsocketConnectionListener,
        ServerSentEventListener,
        FetchTextStreamEventListener,
    ]


@pytest.mark.parametrize(
    "listeners",
    [
        lambda _event: None,
        [lambda _event: None],
    ],
)
def test_invocation_creator_rejects_untyped_listener_callables(listeners):
    with pytest.raises(TypeError, match="must be annotated"):
        InvocationCreator.from_any(
            on_start=lambda _input, _page: None,
            on_completed=lambda _context: None,
            listeners=listeners,
        )


def test_invocation_creator_resolves_forward_referenced_event_annotation():
    def listener(event) -> None:
        pass

    listener.__annotations__["event"] = "HTTPTransaction"
    creator = InvocationCreator.from_any(
        on_start=lambda _input, _page: None,
        on_completed=lambda _context: None,
        listeners=listener,
    )

    assert isinstance(creator.listeners[0], HTTPTransactionListener)
