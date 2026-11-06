from fairybrowser.devtools.models.fetch_text_stream_event import FetchTextStreamEvent
from fairybrowser.devtools.models.http_transaction import HTTPRequest, HTTPTransaction
from fairybrowser.devtools.models.policy import (
    DevtoolsLogPolicy,
    FetchTextStreamEventPredicate,
    HTTPTransactionPredicate,
    ServerSentEventsPredicate,
    WebsocketConnectionPredicate,
)
from fairybrowser.devtools.models.server_sent_events import ServerSentEvent, ServerSentEvents
from fairybrowser.devtools.models.websockets import WebsocketConnection, WebsocketEvent


def test_predicate_lists_use_any_match_for_http_and_websocket_connection():
    transaction = HTTPTransaction(request=HTTPRequest(url="https://example.com", method="GET"))
    connection = WebsocketConnection(
        request_id="ws-1",
        events=[
            WebsocketEvent(request_id="ws-1", event_type="created"),
            WebsocketEvent(request_id="ws-1", event_type="frame_received"),
        ],
    )
    policy = DevtoolsLogPolicy.from_any(
        transaction_predicates=[lambda _: False, HTTPTransactionPredicate(lambda _: True)],
        websocket_connection_predicates=[
            WebsocketConnectionPredicate(lambda _: False),
            lambda connection: any(event.event_type == "frame_received" for event in connection.events),
        ],
    )

    assert policy.should_save_transaction(transaction)
    assert policy.should_save_websocket_connection(connection)


def test_fetch_stream_event_predicates_accept_any_match_and_default_to_all():
    event = FetchTextStreamEvent(
        stream_id="fetch-1",
        event_type="chunk",
        url="https://example.com/stream",
        method="GET",
        status=200,
        chunk_index=0,
        timestamp_ms=1.0,
        elapsed_ms=1.0,
        text="hello",
    )
    policy = DevtoolsLogPolicy.from_any(
        fetch_stream_event_predicates=[
            lambda _: False,
            FetchTextStreamEventPredicate(lambda value: value.url.endswith("/stream")),
        ]
    )

    assert policy.should_save_fetch_stream_event(event)
    assert DevtoolsLogPolicy.from_any().should_save_fetch_stream_event(event)


def test_default_predicates_allow_all_events():
    transaction = HTTPTransaction(request=HTTPRequest(url="https://example.com", method="GET"))
    connection = WebsocketConnection(
        request_id="ws-1",
        events=[WebsocketEvent(request_id="ws-1", event_type="closed")],
    )
    policy = DevtoolsLogPolicy.from_any()

    assert policy.should_save_transaction(transaction)
    assert policy.should_save_websocket_connection(connection)


def test_server_sent_events_predicates_accept_any_match():
    events = ServerSentEvents(
        request_id="sse-1",
        events=[
            ServerSentEvent(request_id="sse-1", timestamp=1.0, event_name="update", data="hello"),
        ],
    )
    policy = DevtoolsLogPolicy.from_any(
        server_sent_events_predicates=[
            lambda _: False,
            ServerSentEventsPredicate(lambda value: value.request_id == "sse-1"),
        ]
    )

    assert policy.should_save_server_sent_events(events)


def test_default_server_sent_events_predicate_saves_all():
    events = ServerSentEvents(request_id="sse-1", events=[])

    assert DevtoolsLogPolicy.from_any().should_save_server_sent_events(events)


def test_explicit_categories_override_policy_mode_defaults():
    policy = DevtoolsLogPolicy.from_any(categories=["fetch_stream"])

    assert policy.categories == frozenset({"fetch_stream"})
