from fairybrowser.devtools.models.websockets import WebSocketConnection
from fairybrowser.devtools.models.http_transaction import HTTPRequest, HTTPTransaction
from fairybrowser.devtools.models.policy import (
    DevtoolsLogPolicy,
    HTTPTransactionPredicate,
    WebSocketConnectionPredicate,
)
from fairybrowser.devtools.models.websockets import WebSocketEvent


def test_predicate_lists_use_any_match_for_http_and_websocket_connection():
    transaction = HTTPTransaction(request=HTTPRequest(url="https://example.com", method="GET"))
    connection = WebSocketConnection(
        request_id="ws-1",
        events=[
            WebSocketEvent(request_id="ws-1", event_type="created"),
            WebSocketEvent(request_id="ws-1", event_type="frame_received"),
        ],
    )
    policy = DevtoolsLogPolicy.from_any(
        transaction_predicates=[lambda _: False, HTTPTransactionPredicate(lambda _: True)],
        websocket_connection_predicates=[
            WebSocketConnectionPredicate(lambda _: False),
            lambda connection: any(event.event_type == "frame_received" for event in connection.events),
        ],
    )

    assert policy.should_save_transaction(transaction)
    assert policy.should_save_websocket_connection(connection)


def test_default_predicates_allow_all_events():
    transaction = HTTPTransaction(request=HTTPRequest(url="https://example.com", method="GET"))
    connection = WebSocketConnection(
        request_id="ws-1",
        events=[WebSocketEvent(request_id="ws-1", event_type="closed")],
    )
    policy = DevtoolsLogPolicy.from_any()

    assert policy.should_save_transaction(transaction)
    assert policy.should_save_websocket_connection(connection)
