import time
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event
from typing import Any, Callable, Final, Literal, Mapping, Protocol, Self, Sequence, assert_never, cast

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


@dataclass(frozen=True)
class InvocationContext[T]:
    """Invocation state and the signal used to indicate completion."""

    state: dict[str, Any] = field(default_factory=dict)
    completion_event: Event = field(default_factory=Event)

    def completion(self) -> None:
        self.completion_event.set()


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
    import inspect

    signature = inspect.signature(listener)

    try:
        signature.bind(None, None)
    except TypeError:
        signature.bind(None)
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


type EventCallable = ListenerCallable[FetchTextStreamEvent]

type InvocationListener = (
    HTTPTransactionListener | WebsocketConnectionListener | ServerSentEventListener | FetchTextStreamEventListener
)
_LISTENER_TYPE_TO_CATEGORIES: Final[Mapping[type[InvocationListener], LogCategory]] = {
    HTTPTransactionListener: "http",
    WebsocketConnectionListener: "websocket",
    ServerSentEventListener: "event_source",
    FetchTextStreamEventListener: "fetch_stream",
}


def _get_required_categories(listeners: Sequence[InvocationListener]) -> Sequence[LogCategory]:
    return tuple({_LISTENER_TYPE_TO_CATEGORIES[type(listener)] for listener in listeners})


class InvocationCreatorProtocol[S, T](Protocol):
    def start(self, input: S, page: Page, context: InvocationContext) -> None:
        """This is assured that `page` is generated"""
        ...

    @property
    def listeners(self) -> Sequence[InvocationListener]: ...

    def finalize(self, page: Page, context: InvocationContext) -> T:
        """This function returns the result of Invocation."""
        ...


@dataclass(frozen=True)
class InvocationCreator[S, T]:
    on_start: Callable[[S, Page, InvocationContext], None]
    on_completion: Callable[[Page, InvocationContext], T]
    listeners: Sequence[InvocationListener]

    @classmethod
    def from_any(
        cls,
        on_start: Callable[[S, Page, InvocationContext], None] | Callable[[S, Page], None],
        on_completion: Callable[[Page, InvocationContext], T] | Callable[[InvocationContext], T],
        listeners: Sequence[InvocationListener | EventCallable] | EventCallable | InvocationListener,
    ) -> Self:
        return cls(
            on_start=cls._resolve_on_start(on_start),
            on_completion=cls._resolve_on_completion(on_completion),
            listeners=cls._resolve_listeners(listeners),
        )

    def start(self, input: S, page: Page, context: InvocationContext) -> None:
        self.on_start(input, page, context)

    def finalize(self, page: Page, context: InvocationContext) -> T:
        return self.on_completion(page, context)

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
    def _resolve_on_completion(
        cls, on_completion: Callable[[Page, InvocationContext], T] | Callable[[InvocationContext], T]
    ) -> Callable[[Page, InvocationContext], T]:
        import inspect

        signature = inspect.signature(on_completion)

        try:
            signature.bind(None, None)
        except TypeError:
            signature.bind(None)
            one_argument = cast(Callable[[InvocationContext], T], on_completion)
            normalized: Callable[[Page, InvocationContext], T] = lambda page, context: one_argument(  # noqa
                context,
            )
        else:
            normalized = cast(Callable[[Page, InvocationContext], T], on_completion)
        return normalized

    @classmethod
    def _resolve_listeners(
        cls,
        listeners: Sequence[InvocationListener | EventCallable] | EventCallable | InvocationListener,
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
            return (FetchTextStreamEventListener.from_any(cast(EventCallable, listeners)),)

        resolved: list[InvocationListener] = []
        for listener in listeners:
            if isinstance(listener, listener_types):
                resolved.append(listener)
            elif callable(listener):
                resolved.append(FetchTextStreamEventListener.from_any(listener))
            else:
                raise TypeError(f"Unsupported invocation listener: {type(listener).__name__}")
        return tuple(resolved)


class _CompletionWaiter:
    def __init__(self, completion_event: Event, timeout: float | None):
        self._completion_event = completion_event
        self._timeout = timeout

    def wait(self, page: Page) -> None:
        deadline = time.monotonic() + self._timeout if (self._timeout is not None) else None
        while not self._completion_event.is_set():
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"Timeout occurs for waiting the set of `completion_event`, {self._timeout=}")
                page.wait_for_timeout(min(100, max(1, int(remaining * 1000))))
            else:
                page.wait_for_timeout(100)


class InvocationExecutor[S, T]:
    def __init__(self, invocation_creator: InvocationCreatorProtocol) -> None:
        self._invocation_creator = invocation_creator

    @classmethod
    def from_any(cls, invocation_creator: InvocationCreatorProtocol) -> Self:
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
            _ = self._subscribe(devtools_service, context, listeners)
            devtools_service.start()
            self._invocation_creator.start(input=input, page=page, context=context)
            _CompletionWaiter(context.completion_event, configuration.timeout).wait(page)

            return self._invocation_creator.finalize(page, context)

    def _subscribe(
        self, service: DevtoolsService, context: InvocationContext, listeners: Sequence[InvocationListener]
    ) -> Sequence[Disposable]:
        return [self._subscribe_listener(service, listener, context) for listener in listeners]

    def _subscribe_listener(
        self, service: DevtoolsService, listener: InvocationListener, context: InvocationContext
    ) -> Disposable:
        match listener:
            case HTTPTransactionListener():
                return service.on_http_transaction.subscribe(lambda event: listener.listener(event, context))
            case WebsocketConnectionListener():
                return service.on_websocket_connection.subscribe(lambda event: listener.listener(event, context))
            case ServerSentEventListener():
                return service.on_server_sent_event.subscribe(lambda event: listener.listener(event, context))
            case FetchTextStreamEventListener():
                return service.on_fetch_stream_event.subscribe(lambda event: listener.listener(event, context))
            case _:
                assert_never(listener)
