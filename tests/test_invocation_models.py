import pytest

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
    ServerSentEventListener,
    WebsocketConnectionListener,
)
from fairybrowser.models import BrowserInfo


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


def test_invocation_creator_from_any_resolves_single_fetch_listener():
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
        on_completion=lambda _context: None,
        listeners=lambda item: received.append(item),
    )

    assert len(creator.listeners) == 1
    assert isinstance(creator.listeners[0], FetchTextStreamEventListener)
    creator.listeners[0].listener(event, InvocationContext())
    assert received == [event]


def test_invocation_creator_from_any_resolves_mixed_listener_sequence():
    http_listener = HTTPTransactionListener.from_any(lambda _transaction: None)

    def fetch_listener(_event):
        return None

    creator = InvocationCreator.from_any(
        on_start=lambda _input, _page: None,
        on_completion=lambda _context: None,
        listeners=[http_listener, fetch_listener],
    )

    assert creator.listeners[0] is http_listener
    assert isinstance(creator.listeners[1], FetchTextStreamEventListener)
