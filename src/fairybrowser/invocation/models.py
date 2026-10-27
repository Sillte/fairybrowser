import math
import time
from dataclasses import dataclass, field
from inspect import Parameter, signature
from pathlib import Path
from threading import Condition, Event, Lock
from typing import (
    Any,
    Callable,
    Final,
    Literal,
    Mapping,
    Protocol,
    Self,
    Sequence,
    assert_never,
    cast,
    get_type_hints,
    runtime_checkable,
)

from playwright.sync_api import Page

from fairybrowser.devtools import (
    DevtoolsLogPolicy,
    DevtoolsService,
    FetchTextStreamEvent,
    HTTPTransaction,
    LogCategory,
    ServerSentEvent,
    WebsocketConnection,
)
from fairybrowser.models import BrowserInfo
from fairybrowser.runners import sync_page
from fairybrowser.shared.event import Disposable

type ListenerEventType = HTTPTransaction | WebsocketConnection | ServerSentEvent | FetchTextStreamEvent


class ListenerEventException(Exception):
    """Raised when a listener reports an error event."""

    def __init__(self, event: ListenerEventType) -> None:
        self.event = event
        super().__init__(f"Invocation listener received an error event: {type(event).__name__}")


@dataclass(frozen=True)
class TimerEvent:
    tick_count: int
    scheduled_at: float
    fired_at: float


@dataclass
class _TimerEventSlot:
    value: TimerEvent | None = None


@dataclass
class _ListenerState:
    result: Any = None
    active_count: int = 0
    closed: bool = False


_NO_LISTENER_RESULT = object()


@dataclass(frozen=True)
class InvocationContext[T]:
    """Invocation state and the signal used to indicate completion."""

    state: dict[str, Any] = field(default_factory=dict)
    completion_event: Event = field(default_factory=Event)
    _errors: list[BaseException] = field(default_factory=list, repr=False)
    _error_lock: Lock = field(default_factory=Lock, repr=False)
    _timer_event_slot: _TimerEventSlot = field(default_factory=_TimerEventSlot, init=False, repr=False, compare=False)
    _listener_condition: Condition = field(default_factory=Condition, init=False, repr=False, compare=False)
    _listener_state: _ListenerState = field(default_factory=_ListenerState, init=False, repr=False, compare=False)

    @property
    def timer_event(self) -> TimerEvent | None:
        return self._timer_event_slot.value

    def _set_timer_event(self, event: TimerEvent) -> None:
        self._timer_event_slot.value = event

    @property
    def listener_result(self) -> Any:
        """Return the result of the last listener that completed."""
        with self._listener_condition:
            return self._listener_state.result

    def _begin_listener(self) -> bool:
        with self._listener_condition:
            if self._listener_state.closed:
                return False
            self._listener_state.active_count += 1
            return True

    def _finish_listener(self, result: Any = _NO_LISTENER_RESULT) -> None:
        with self._listener_condition:
            if result is not _NO_LISTENER_RESULT:
                self._listener_state.result = result
            self._listener_state.active_count -= 1
            if self._listener_state.active_count == 0:
                self._listener_condition.notify_all()

    def _finish_listeners(self) -> None:
        with self._listener_condition:
            self._listener_state.closed = True
            self._listener_condition.notify_all()
            while self._listener_state.active_count:
                self._listener_condition.wait()

    def complete(self) -> None:
        self.completion_event.set()

    def fail(self, error: BaseException | ListenerEventType) -> None:
        match error:
            case BaseException():
                failure = error
            case HTTPTransaction() | WebsocketConnection() | ServerSentEvent() | FetchTextStreamEvent():
                failure = ListenerEventException(error)
            case _:
                assert_never(error)

        with self._error_lock:
            if not self._errors:
                self._errors.append(failure)
            self.completion_event.set()

    @property
    def error(self) -> BaseException | None:
        with self._error_lock:
            return self._errors[0] if self._errors else None


@dataclass(frozen=True)
class InvocationConfiguration:
    """Configuration for an invocation."""

    timeout: float | None = field(default=120)
    browser_info: BrowserInfo | None = field(default=None)

    @classmethod
    def from_any(cls, configuration: Self | BrowserInfo | None = None) -> Self:
        if configuration is None:
            return cls()
        if isinstance(configuration, BrowserInfo):
            return cls(browser_info=configuration)
        if isinstance(configuration, cls):
            return configuration
        raise TypeError(f"Unsupported invocation configuration: {type(configuration).__name__}")


def _resolve_listener_callable[T](
    listener: Callable[[T], Any] | Callable[[T, InvocationContext], Any],
) -> Callable[[T, InvocationContext], Any]:
    listener_signature = signature(listener)

    try:
        listener_signature.bind(None, None)
    except TypeError:
        listener_signature.bind(None)
        one_argument = cast(Callable[[T], Any], listener)

        def normalized(transaction: T, _context: InvocationContext) -> Any:
            return one_argument(transaction)
    else:
        normalized = cast(Callable[[T, InvocationContext], Any], listener)
    return normalized


type ListenerCallable[T] = Callable[[T], Any] | Callable[[T, InvocationContext], Any]


@dataclass(frozen=True)
class HTTPTransactionListener:
    listener: Callable[[HTTPTransaction, InvocationContext], Any]
    kind: Literal["http"] = "http"

    @classmethod
    def from_any(cls, listener: ListenerCallable[HTTPTransaction]) -> Self:
        return cls(listener=_resolve_listener_callable(listener))


@dataclass(frozen=True)
class WebsocketConnectionListener:
    listener: Callable[[WebsocketConnection, InvocationContext], Any]
    kind: Literal["websocket"] = "websocket"

    @classmethod
    def from_any(cls, listener: ListenerCallable[WebsocketConnection]) -> Self:
        return cls(listener=_resolve_listener_callable(listener))


@dataclass(frozen=True)
class ServerSentEventListener:
    listener: Callable[[ServerSentEvent, InvocationContext], Any]
    kind: Literal["event_source"] = "event_source"

    @classmethod
    def from_any(cls, listener: ListenerCallable[ServerSentEvent]) -> Self:
        return cls(listener=_resolve_listener_callable(listener))


@dataclass(frozen=True)
class FetchTextStreamEventListener:
    listener: Callable[[FetchTextStreamEvent, InvocationContext], Any]
    kind: Literal["fetch_stream"] = "fetch_stream"

    @classmethod
    def from_any(cls, listener: ListenerCallable[FetchTextStreamEvent]) -> Self:
        return cls(listener=_resolve_listener_callable(listener))


@dataclass(frozen=True)
class TimerEventListener:
    interval: float
    listener: Callable[[Page, InvocationContext], Any]
    kind: Literal["timer"] = "timer"

    def __post_init__(self) -> None:
        if not math.isfinite(self.interval) or self.interval <= 0:
            raise ValueError("Timer interval must be a finite positive number")

    @classmethod
    def from_any(
        cls,
        listener: Callable[[Page, InvocationContext], Any] | Callable[[InvocationContext], Any],
        interval: float = 1.0,
    ) -> Self:
        listener_signature = signature(listener)
        try:
            listener_signature.bind(None, None)
        except TypeError:
            listener_signature.bind(None)
            one_argument = cast(Callable[[Page], Any], listener)

            def normalized(transaction: Page, _context: InvocationContext) -> Any:
                return one_argument(transaction)
        else:
            normalized = cast(Callable[[Page, InvocationContext], Any], listener)  # type: ignore
        return cls(interval=interval, listener=normalized)


type DevtoolsListener = (
    HTTPTransactionListener | WebsocketConnectionListener | ServerSentEventListener | FetchTextStreamEventListener
)
type InvocationListener = DevtoolsListener | TimerEventListener
type InvocationListenerLike = InvocationListener | Callable[..., object]
type InvocationListeners = InvocationListenerLike | Sequence[InvocationListenerLike]


def _resolve_listener(listener: Callable[..., object]) -> InvocationListener:
    try:
        parameters = signature(listener).parameters.values()
        first_parameter = next(
            parameter
            for parameter in parameters
            if parameter.kind in (Parameter.POSITIONAL_ONLY, Parameter.POSITIONAL_OR_KEYWORD)
        )
        event_type = get_type_hints(listener).get(first_parameter.name)
    except StopIteration as error:
        raise TypeError("Listener must have a first parameter annotated with a supported event type") from error
    except (NameError, TypeError) as error:
        raise TypeError("Listener event annotation could not be resolved") from error

    match event_type:
        case type() as annotated_type if annotated_type is HTTPTransaction:
            return HTTPTransactionListener.from_any(cast(ListenerCallable[HTTPTransaction], listener))
        case type() as annotated_type if annotated_type is WebsocketConnection:
            return WebsocketConnectionListener.from_any(cast(ListenerCallable[WebsocketConnection], listener))
        case type() as annotated_type if annotated_type is ServerSentEvent:
            return ServerSentEventListener.from_any(cast(ListenerCallable[ServerSentEvent], listener))
        case type() as annotated_type if annotated_type is FetchTextStreamEvent:
            return FetchTextStreamEventListener.from_any(cast(ListenerCallable[FetchTextStreamEvent], listener))
    raise TypeError(
        "Listener's first parameter must be annotated as HTTPTransaction, WebsocketConnection, "
        "ServerSentEvent, or FetchTextStreamEvent"
    )


def _split_listeners(
    listeners: Sequence[InvocationListener],
) -> tuple[Sequence[DevtoolsListener], Sequence[TimerEventListener]]:
    devtools_listeners: list[DevtoolsListener] = []
    timer_listeners: list[TimerEventListener] = []
    for listener in listeners:
        if isinstance(listener, TimerEventListener):
            timer_listeners.append(listener)
        else:
            devtools_listeners.append(listener)
    return tuple(devtools_listeners), tuple(timer_listeners)


_LISTENER_TYPE_TO_CATEGORIES: Final[Mapping[type[DevtoolsListener], LogCategory]] = {
    HTTPTransactionListener: "http",
    WebsocketConnectionListener: "websocket",
    ServerSentEventListener: "event_source",
    FetchTextStreamEventListener: "fetch_stream",
}


def _get_required_categories(listeners: Sequence[DevtoolsListener]) -> Sequence[LogCategory]:
    return tuple({_LISTENER_TYPE_TO_CATEGORIES[type(listener)] for listener in listeners})


@runtime_checkable
class InvocationProtocol[S, T](Protocol):
    def start(self, input: S, page: Page, context: InvocationContext) -> None:
        """This is assured that `page` is generated"""
        ...

    @property
    def listeners(self) -> Sequence[InvocationListener]: ...

    def on_completed(self, page: Page, context: InvocationContext) -> T:
        """Return the invocation result after completion."""
        ...


@dataclass(frozen=True)
class InvocationCreator[S, T]:
    on_start: Callable[[S, Page, InvocationContext], None]
    _on_completed_callback: Callable[[Page, InvocationContext], T]
    listeners: Sequence[InvocationListener]

    @classmethod
    def from_any(
        cls,
        on_start: Callable[[S, Page, InvocationContext], None] | Callable[[S, Page], None],
        on_completed: Callable[[Page, InvocationContext], T] | Callable[[InvocationContext], T] | None = None,
        listeners: InvocationListeners = (),
    ) -> Self:
        """Create an invocation, resolving raw listener callbacks from their first parameter annotation."""
        completion_callback = (
            cls._resolve_on_completed(on_completed)
            if on_completed is not None
            else lambda _page, context: cast(T, context.listener_result)
        )
        return cls(
            on_start=cls._resolve_on_start(on_start),
            _on_completed_callback=completion_callback,
            listeners=cls._resolve_listeners(listeners),
        )

    def start(self, input: S, page: Page, context: InvocationContext) -> None:
        self.on_start(input, page, context)

    def on_completed(self, page: Page, context: InvocationContext) -> T:
        return self._on_completed_callback(page, context)

    @classmethod
    def _resolve_on_start(
        cls, on_start: Callable[[S, Page, InvocationContext], None] | Callable[[S, Page], None]
    ) -> Callable[[S, Page, InvocationContext], None]:
        import inspect

        signature = inspect.signature(on_start)

        try:
            signature.bind(None, None, None)
        except TypeError:
            signature.bind(None, None)
            two_argument = cast(Callable[[S, Page], None], on_start)
            normalized: Callable[[S, Page, InvocationContext], None] = lambda input, page, _context: two_argument(  # noqa
                input,
                page,
            )
        else:
            normalized = cast(Callable[[S, Page, InvocationContext], None], on_start)
        return normalized

    @classmethod
    def _resolve_on_completed(
        cls, on_completed: Callable[[Page, InvocationContext], T] | Callable[[InvocationContext], T]
    ) -> Callable[[Page, InvocationContext], T]:
        import inspect

        signature = inspect.signature(on_completed)

        try:
            signature.bind(None, None)
        except TypeError:
            signature.bind(None)
            one_argument = cast(Callable[[InvocationContext], T], on_completed)
            normalized: Callable[[Page, InvocationContext], T] = lambda page, context: one_argument(  # noqa
                context,
            )
        else:
            normalized = cast(Callable[[Page, InvocationContext], T], on_completed)
        return normalized

    @classmethod
    def _resolve_listeners(
        cls,
        listeners: InvocationListeners,
    ) -> Sequence[InvocationListener]:
        listener_types = (
            HTTPTransactionListener,
            WebsocketConnectionListener,
            ServerSentEventListener,
            FetchTextStreamEventListener,
            TimerEventListener,
        )
        if isinstance(listeners, listener_types):
            return (listeners,)
        if callable(listeners):
            return (_resolve_listener(listeners),)
        if not isinstance(listeners, Sequence):
            raise TypeError("listeners must be a listener callback or a sequence of listener callbacks")
        resolved: list[InvocationListener] = []
        for listener in listeners:
            if isinstance(listener, listener_types):
                resolved.append(listener)
            elif callable(listener):
                resolved.append(_resolve_listener(listener))
            else:
                raise TypeError(f"Unsupported invocation listener: {type(listener).__name__}")
        return tuple(resolved)


class _CompletionWaiter:
    def __init__(
        self,
        context: InvocationContext,
        timeout: float | None,
        timer_listeners: Sequence[TimerEventListener] = (),
    ):
        self._context = context
        self._timeout = timeout
        self._timer_listeners = timer_listeners

    def wait(self, page: Page) -> None:
        started_at = time.monotonic()
        deadline = started_at + self._timeout if self._timeout is not None else None
        timers = [(listener, started_at + listener.interval, 0) for listener in self._timer_listeners]
        while not self._context.completion_event.is_set():
            now = time.monotonic()
            if deadline is not None and deadline - now <= 0:
                raise TimeoutError(f"Timeout occurs for waiting the set of `completion_event`, {self._timeout=}")

            due_timers = [index for index, (_, scheduled_at, _) in enumerate(timers) if scheduled_at <= now]
            if due_timers:
                for index in due_timers:
                    listener, scheduled_at, tick_count = timers[index]
                    fired_at = time.monotonic()
                    self._context._set_timer_event(
                        TimerEvent(
                            tick_count=tick_count + 1,
                            scheduled_at=scheduled_at,
                            fired_at=fired_at,
                        )
                    )
                    listener_started = self._context._begin_listener()
                    if not listener_started:
                        break
                    result = _NO_LISTENER_RESULT
                    try:
                        result = listener.listener(page, self._context)
                    except Exception as error:
                        self._context.fail(error)
                    finally:
                        self._context._finish_listener(result)
                    timers[index] = (listener, time.monotonic() + listener.interval, tick_count + 1)
                    if self._context.completion_event.is_set():
                        break
                continue

            wait_seconds = 0.1
            if deadline is not None:
                wait_seconds = min(wait_seconds, deadline - now)
            if timers:
                next_timer = min(scheduled_at for _, scheduled_at, _ in timers)
                wait_seconds = min(wait_seconds, max(0, next_timer - now))
            page.wait_for_timeout(max(1, int(wait_seconds * 1000)))

        self._context._finish_listeners()
        error = self._context.error
        if error is not None:
            raise error


class InvocationExecutor[S, T]:
    def __init__(self, invocation_creator: InvocationProtocol) -> None:
        self._invocation_creator = invocation_creator

    @classmethod
    def from_any(cls, invocation_creator: InvocationProtocol) -> Self:
        return cls(invocation_creator=invocation_creator)

    def invoke(
        self, input: S, configuration: InvocationConfiguration | None = None, *, output_folder: Path | None = None
    ) -> T:
        configuration = configuration or InvocationConfiguration.from_any()
        context = InvocationContext()
        devtools_listeners, timer_listeners = _split_listeners(self._invocation_creator.listeners)
        policy = DevtoolsLogPolicy.from_any(categories=_get_required_categories(devtools_listeners))

        with sync_page(browser_info=configuration.browser_info) as page:
            devtools_service = DevtoolsService(page=page, policy=policy, save_memory=True, output_folder=output_folder)
            subscriptions = self._subscribe(devtools_service, context, devtools_listeners)
            try:
                devtools_service.start()
                self._invocation_creator.start(input=input, page=page, context=context)
                _CompletionWaiter(context, configuration.timeout, timer_listeners).wait(page)

                return self._invocation_creator.on_completed(page, context)
            finally:
                try:
                    for subscription in subscriptions:
                        subscription.dispose()
                finally:
                    devtools_service.terminate()

    def _subscribe(
        self, service: DevtoolsService, context: InvocationContext, listeners: Sequence[DevtoolsListener]
    ) -> Sequence[Disposable]:
        return [self._subscribe_listener(service, listener, context) for listener in listeners]

    def _subscribe_listener(
        self, service: DevtoolsService, listener: DevtoolsListener, context: InvocationContext
    ) -> Disposable:
        def notify(event: Any) -> None:
            if not context._begin_listener():
                return
            result = _NO_LISTENER_RESULT
            try:
                result = listener.listener(event, context)
            except Exception as error:
                context.fail(error)
            finally:
                context._finish_listener(result)

        match listener:
            case HTTPTransactionListener():
                return service.on_http_transaction.subscribe(notify)
            case WebsocketConnectionListener():
                return service.on_websocket_connection.subscribe(notify)
            case ServerSentEventListener():
                return service.on_server_sent_event.subscribe(notify)
            case FetchTextStreamEventListener():
                return service.on_fetch_stream_event.subscribe(notify)
            case _:
                assert_never(listener)
