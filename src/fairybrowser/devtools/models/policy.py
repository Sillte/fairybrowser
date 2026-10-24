from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal, Self, cast

from .http_transaction import HTTPTransaction
from .server_sent_events import ServerSentEvents
from .websockets import WebSocketConnection

LogCategory = Literal["http", "event_source", "fetch_stream", "websocket", "console"]
PolicyMode = Literal["all", "default"]

POLICY_CATEGORIES: dict[PolicyMode, set[LogCategory]] = {
    "all": {"http", "event_source", "fetch_stream", "websocket", "console"},
    "default": {"http", "event_source", "websocket"},
}


type HTTPTransactionPredicateCallable = Callable[[HTTPTransaction], bool]
type WebSocketConnectionPredicateCallable = Callable[[WebSocketConnection], bool]
type ServerSentEventsPredicateCallable = Callable[[ServerSentEvents], bool]


def _always_save_transaction(_: HTTPTransaction) -> bool:
    return True


def _always_save_websocket_connection(_: WebSocketConnection) -> bool:
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
class WebSocketConnectionPredicate:
    function: WebSocketConnectionPredicateCallable

    @classmethod
    def from_any(
        cls,
        predicate: WebSocketConnectionPredicateCallable | WebSocketConnectionPredicate | None = None,
    ) -> Self:
        if predicate is None:
            predicate = _always_save_websocket_connection
        elif isinstance(predicate, WebSocketConnectionPredicate):
            predicate = predicate.function
        return cls(function=predicate)

    def __call__(self, connection: WebSocketConnection) -> bool:
        return self.function(connection)


type WebSocketConnectionPredicatesLike = (
    Sequence[WebSocketConnectionPredicateCallable | WebSocketConnectionPredicate]
    | WebSocketConnectionPredicateCallable
    | WebSocketConnectionPredicate
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
    websocket_connection_predicates: Sequence[WebSocketConnectionPredicate]
    server_sent_events_predicates: Sequence[ServerSentEventsPredicate]

    @classmethod
    def from_any(
        cls,
        categories: Sequence[LogCategory] | None = None,
        transaction_predicates: HTTPTransactionPredicatesLike | None = None,
        websocket_connection_predicates: WebSocketConnectionPredicatesLike | None = None,
        server_sent_events_predicates: ServerSentEventsPredicatesLike | None = None,
        *,
        policy_mode: PolicyMode = "default",
    ) -> Self:
        enabled_categories = POLICY_CATEGORIES[policy_mode] if categories is None else set(categories)
        transaction_filters = _normalize_transaction_predicates(transaction_predicates)
        websocket_filters = _normalize_websocket_connection_predicates(websocket_connection_predicates)
        server_sent_events_filters = _normalize_server_sent_events_predicates(server_sent_events_predicates)

        return cls(
            categories=frozenset(enabled_categories),
            transaction_predicates=transaction_filters,
            websocket_connection_predicates=websocket_filters,
            server_sent_events_predicates=server_sent_events_filters,
        )

    def should_save_transaction(self, transaction: HTTPTransaction) -> bool:
        return any(predicate(transaction) for predicate in self.transaction_predicates)

    def should_save_websocket_connection(self, connection: WebSocketConnection) -> bool:
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


def _normalize_websocket_connection_predicates(
    value: WebSocketConnectionPredicatesLike | None,
) -> list[WebSocketConnectionPredicate]:
    if value is None:
        return [WebSocketConnectionPredicate.from_any()]
    if isinstance(value, WebSocketConnectionPredicate):
        return [value]
    if callable(value):
        return [WebSocketConnectionPredicate.from_any(cast(WebSocketConnectionPredicateCallable, value))]
    return [WebSocketConnectionPredicate.from_any(item) for item in value]


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
