from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Literal, Self, cast

from .fetch_text_stream_event import FetchTextStreamEvent
from .http_transaction import HTTPTransaction
from .server_sent_events import ServerSentEvents
from .websockets import WebsocketConnection

LogCategory = Literal["http", "event_source", "fetch_stream", "websocket", "console"]
PolicyMode = Literal["all", "default"]

POLICY_CATEGORIES: dict[PolicyMode, set[LogCategory]] = {
    "all": {"http", "event_source", "fetch_stream", "websocket", "console"},
    "default": {"http", "event_source", "websocket"},
}


type HTTPTransactionPredicateCallable = Callable[[HTTPTransaction], bool]
type FetchTextStreamEventPredicateCallable = Callable[[FetchTextStreamEvent], bool]
type WebsocketConnectionPredicateCallable = Callable[[WebsocketConnection], bool]
type ServerSentEventsPredicateCallable = Callable[[ServerSentEvents], bool]


def _always_save_transaction(_: HTTPTransaction) -> bool:
    return True


def _always_save_fetch_stream_event(_: FetchTextStreamEvent) -> bool:
    return True


def _always_save_websocket_connection(_: WebsocketConnection) -> bool:
    return True


def _always_save_server_sent_events(_: ServerSentEvents) -> bool:
    return True


@dataclass(frozen=True)
class HTTPTransactionPredicate:
    function: HTTPTransactionPredicateCallable

    @classmethod
    def from_any(
        cls,
        predicate: HTTPTransactionPredicateCallable | HTTPTransactionPredicate | None = None,
    ) -> Self:
        if predicate is None:
            predicate = _always_save_transaction
        elif isinstance(predicate, HTTPTransactionPredicate):
            predicate = predicate.function
        return cls(function=predicate)

    def __call__(self, transaction: HTTPTransaction) -> bool:
        return self.function(transaction)


type HTTPTransactionPredicatesLike = (
    Sequence[HTTPTransactionPredicateCallable | HTTPTransactionPredicate]
    | HTTPTransactionPredicateCallable
    | HTTPTransactionPredicate
)


@dataclass(frozen=True)
class FetchTextStreamEventPredicate:
    function: FetchTextStreamEventPredicateCallable

    @classmethod
    def from_any(
        cls,
        predicate: FetchTextStreamEventPredicateCallable | FetchTextStreamEventPredicate | None = None,
    ) -> Self:
        if predicate is None:
            predicate = _always_save_fetch_stream_event
        elif isinstance(predicate, FetchTextStreamEventPredicate):
            predicate = predicate.function
        return cls(function=predicate)

    def __call__(self, event: FetchTextStreamEvent) -> bool:
        return self.function(event)


type FetchTextStreamEventPredicatesLike = (
    Sequence[FetchTextStreamEventPredicateCallable | FetchTextStreamEventPredicate]
    | FetchTextStreamEventPredicateCallable
    | FetchTextStreamEventPredicate
)


@dataclass(frozen=True)
class WebsocketConnectionPredicate:
    function: WebsocketConnectionPredicateCallable

    @classmethod
    def from_any(
        cls,
        predicate: WebsocketConnectionPredicateCallable | WebsocketConnectionPredicate | None = None,
    ) -> Self:
        if predicate is None:
            predicate = _always_save_websocket_connection
        elif isinstance(predicate, WebsocketConnectionPredicate):
            predicate = predicate.function
        return cls(function=predicate)

    def __call__(self, connection: WebsocketConnection) -> bool:
        return self.function(connection)


type WebsocketConnectionPredicatesLike = (
    Sequence[WebsocketConnectionPredicateCallable | WebsocketConnectionPredicate]
    | WebsocketConnectionPredicateCallable
    | WebsocketConnectionPredicate
)


@dataclass(frozen=True)
class ServerSentEventsPredicate:
    function: ServerSentEventsPredicateCallable

    @classmethod
    def from_any(
        cls,
        predicate: ServerSentEventsPredicateCallable | ServerSentEventsPredicate | None = None,
    ) -> Self:
        if predicate is None:
            predicate = _always_save_server_sent_events
        elif isinstance(predicate, ServerSentEventsPredicate):
            predicate = predicate.function
        return cls(function=predicate)

    def __call__(self, events: ServerSentEvents) -> bool:
        return self.function(events)


type ServerSentEventsPredicatesLike = (
    Sequence[ServerSentEventsPredicateCallable | ServerSentEventsPredicate]
    | ServerSentEventsPredicateCallable
    | ServerSentEventsPredicate
)


@dataclass(frozen=True)
class DevtoolsLogPolicy:
    categories: frozenset[LogCategory]
    transaction_predicates: Sequence[HTTPTransactionPredicate]
    websocket_connection_predicates: Sequence[WebsocketConnectionPredicate]
    server_sent_events_predicates: Sequence[ServerSentEventsPredicate]
    fetch_stream_event_predicates: Sequence[FetchTextStreamEventPredicate] = field(
        default_factory=lambda: (FetchTextStreamEventPredicate.from_any(),)
    )

    @classmethod
    def from_any(
        cls,
        categories: Sequence[LogCategory] | None = None,
        transaction_predicates: HTTPTransactionPredicatesLike | None = None,
        websocket_connection_predicates: WebsocketConnectionPredicatesLike | None = None,
        server_sent_events_predicates: ServerSentEventsPredicatesLike | None = None,
        fetch_stream_event_predicates: FetchTextStreamEventPredicatesLike | None = None,
        *,
        policy_mode: PolicyMode = "default",
    ) -> Self:
        enabled_categories = POLICY_CATEGORIES[policy_mode] if categories is None else set(categories)
        transaction_filters = _normalize_transaction_predicates(transaction_predicates)
        fetch_stream_filters = _normalize_fetch_stream_event_predicates(fetch_stream_event_predicates)
        websocket_filters = _normalize_websocket_connection_predicates(websocket_connection_predicates)
        server_sent_events_filters = _normalize_server_sent_events_predicates(server_sent_events_predicates)

        return cls(
            categories=frozenset(enabled_categories),
            transaction_predicates=transaction_filters,
            fetch_stream_event_predicates=fetch_stream_filters,
            websocket_connection_predicates=websocket_filters,
            server_sent_events_predicates=server_sent_events_filters,
        )

    def should_save_transaction(self, transaction: HTTPTransaction) -> bool:
        return any(predicate(transaction) for predicate in self.transaction_predicates)

    def should_save_fetch_stream_event(self, event: FetchTextStreamEvent) -> bool:
        return any(predicate(event) for predicate in self.fetch_stream_event_predicates)

    def should_save_websocket_connection(self, connection: WebsocketConnection) -> bool:
        return any(predicate(connection) for predicate in self.websocket_connection_predicates)

    def should_save_server_sent_events(self, events: ServerSentEvents) -> bool:
        return any(predicate(events) for predicate in self.server_sent_events_predicates)


def _normalize_transaction_predicates(
    value: HTTPTransactionPredicatesLike | None,
) -> list[HTTPTransactionPredicate]:
    if value is None:
        return [HTTPTransactionPredicate.from_any()]
    if isinstance(value, HTTPTransactionPredicate):
        return [value]
    if callable(value):
        return [HTTPTransactionPredicate.from_any(cast(HTTPTransactionPredicateCallable, value))]
    return [HTTPTransactionPredicate.from_any(item) for item in value]


def _normalize_fetch_stream_event_predicates(
    value: FetchTextStreamEventPredicatesLike | None,
) -> list[FetchTextStreamEventPredicate]:
    if value is None:
        return [FetchTextStreamEventPredicate.from_any()]
    if isinstance(value, FetchTextStreamEventPredicate):
        return [value]
    if callable(value):
        return [FetchTextStreamEventPredicate.from_any(cast(FetchTextStreamEventPredicateCallable, value))]
    return [FetchTextStreamEventPredicate.from_any(item) for item in value]


def _normalize_websocket_connection_predicates(
    value: WebsocketConnectionPredicatesLike | None,
) -> list[WebsocketConnectionPredicate]:
    if value is None:
        return [WebsocketConnectionPredicate.from_any()]
    if isinstance(value, WebsocketConnectionPredicate):
        return [value]
    if callable(value):
        return [WebsocketConnectionPredicate.from_any(cast(WebsocketConnectionPredicateCallable, value))]
    return [WebsocketConnectionPredicate.from_any(item) for item in value]


def _normalize_server_sent_events_predicates(
    value: ServerSentEventsPredicatesLike | None,
) -> list[ServerSentEventsPredicate]:
    if value is None:
        return [ServerSentEventsPredicate.from_any()]
    if isinstance(value, ServerSentEventsPredicate):
        return [value]
    if callable(value):
        return [ServerSentEventsPredicate.from_any(cast(ServerSentEventsPredicateCallable, value))]
    return [ServerSentEventsPredicate.from_any(item) for item in value]
