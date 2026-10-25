import time
from dataclasses import dataclass, field
from inspect import Parameter, signature
from pathlib import Path
from threading import Event, Lock
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
class InvocationContext[T]:
    """Invocation state and the signal used to indicate completion."""

    state: dict[str, Any] = field(default_factory=dict)
    completion_event: Event = field(default_factory=Event)
    _errors: list[BaseException] = field(default_factory=list, repr=False)
    _error_lock: Lock = field(default_factory=Lock, repr=False)

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
    listener: Callable[[T], None] | Callable[[T, InvocationContext], None],
) -> Callable[[T, InvocationContext], None]:
    listener_signature = signature(listener)

    try:
        listener_signature.bind(None, None)
    except TypeError:
        listener_signature.bind(None)
        one_argument = cast(Callable[[T], None], listener)
        normalized: Callable[[T, InvocationContext], None] = lambda transaction, _context: one_argument(transaction)  # noqa
    else:
        normalized = cast(Callable[[T, InvocationContext], None], listener)
    return normalized


type ListenerCallable[T] = Callable[[T], None] | Callable[[T, InvocationContext], None]


@dataclass(frozen=True)
class HTTPTransactionListener:
    listener: Callable[[HTTPTransaction, InvocationContext], None]
    kind: Literal["http"] = "http"

    @classmethod
    def from_any(cls, listener: ListenerCallable[HTTPTransaction]) -> Self:
        return cls(listener=_resolve_listener_callable(listener))


@dataclass(frozen=True)
class WebsocketConnectionListener:
    listener: Callable[[WebsocketConnection, InvocationContext], None]
    kind: Literal["websocket"] = "websocket"

    @classmethod
    def from_any(cls, listener: ListenerCallable[WebsocketConnection]) -> Self:
        return cls(listener=_resolve_listener_callable(listener))


@dataclass(frozen=True)
class ServerSentEventListener:
    listener: Callable[[ServerSentEvent, InvocationContext], None]
    kind: Literal["event_source"] = "event_source"

    @classmethod
    def from_any(cls, listener: ListenerCallable[ServerSentEvent]) -> Self:
        return cls(listener=_resolve_listener_callable(listener))


@dataclass(frozen=True)
class FetchTextStreamEventListener:
    listener: Callable[[FetchTextStreamEvent, InvocationContext], None]
    kind: Literal["fetch_stream"] = "fetch_stream"

    @classmethod
    def from_any(cls, listener: ListenerCallable[FetchTextStreamEvent]) -> Self:
        return cls(listener=_resolve_listener_callable(listener))


type InvocationListener = (
    HTTPTransactionListener | WebsocketConnectionListener | ServerSentEventListener | FetchTextStreamEventListener
)
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

_LISTENER_TYPE_TO_CATEGORIES: Final[Mapping[type[InvocationListener], LogCategory]] = {
    HTTPTransactionListener: "http",
    WebsocketConnectionListener: "websocket",
    ServerSentEventListener: "event_source",
    FetchTextStreamEventListener: "fetch_stream",
}


def _get_required_categories(listeners: Sequence[InvocationListener]) -> Sequence[LogCategory]:
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
        on_completed: Callable[[Page, InvocationContext], T] | Callable[[InvocationContext], T],
        listeners: InvocationListeners,
    ) -> Self:
        """Create an invocation, resolving raw listener callbacks from their first parameter annotation."""
        return cls(
            on_start=cls._resolve_on_start(on_start),
            _on_completed_callback=cls._resolve_on_completed(on_completed),
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
        )
        if isinstance(listeners, listener_types):
            return (listeners,)
        if callable(listeners):
            return (_resolve_listener(listeners),)
        if not isinstance(listeners, Sequence):
            raise TypeError(
                "listeners must be a listener callback or a sequence of listener callbacks"
            )
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
    def __init__(self, context: InvocationContext, timeout: float | None):
        self._context = context
        self._timeout = timeout

    def wait(self, page: Page) -> None:
        deadline = time.monotonic() + self._timeout if (self._timeout is not None) else None
        while not self._context.completion_event.is_set():
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"Timeout occurs for waiting the set of `completion_event`, {self._timeout=}")
                page.wait_for_timeout(min(100, max(1, int(remaining * 1000))))
            else:
                page.wait_for_timeout(100)
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
        listeners = self._invocation_creator.listeners
        policy = DevtoolsLogPolicy.from_any(categories=_get_required_categories(listeners))

        with sync_page(browser_info=configuration.browser_info) as page:
            devtools_service = DevtoolsService(page=page, policy=policy, save_memory=True, output_folder=output_folder)
            subscriptions = self._subscribe(devtools_service, context, listeners)
            try:
                devtools_service.start()
                self._invocation_creator.start(input=input, page=page, context=context)
                _CompletionWaiter(context, configuration.timeout).wait(page)

                return self._invocation_creator.on_completed(page, context)
            finally:
                try:
                    for subscription in subscriptions:
                        subscription.dispose()
                finally:
                    devtools_service.terminate()

    def _subscribe(
        self, service: DevtoolsService, context: InvocationContext, listeners: Sequence[InvocationListener]
    ) -> Sequence[Disposable]:
        return [self._subscribe_listener(service, listener, context) for listener in listeners]

    def _subscribe_listener(
        self, service: DevtoolsService, listener: InvocationListener, context: InvocationContext
    ) -> Disposable:
        def notify(event: Any) -> None:
            try:
                listener.listener(event, context)
            except Exception as error:
                context.fail(error)

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
