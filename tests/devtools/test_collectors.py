from collections.abc import Callable
from pathlib import Path
from typing import cast

from playwright.sync_api import Page

from fairybrowser.devtools.collectors import DevtoolsUser
from fairybrowser.devtools.models import FetchStreamEvent
from fairybrowser.devtools.models.policy import DevtoolsLogPolicy
from fairybrowser.devtools.models.server_sent_events import ServerSentEvent
from fairybrowser.devtools.models.websockets import WebSocketEvent


class FakeCDPClient:
    def __init__(self):
        self.handlers: dict[str, Callable[[dict], None]] = {}
        self.handlers_when_enabled: set[str] = set()

    def send(self, method: str, params: dict | None = None):
        self.last_send = (method, params)
        if method == "Network.enable":
            self.handlers_when_enabled = set(self.handlers)
        return {}

    def on(self, event_name: str, handler: Callable[[dict], None]):
        self.handlers[event_name] = handler

    def emit(self, event_name: str, params: dict):
        self.handlers[event_name](params)


class FakePage:
    def __init__(self):
        self.binding = None
        self.init_script = None
        self.evaluated_script = None

    def expose_binding(self, name: str, callback):
        assert name == "__fairybrowser_capture_fetch_stream"
        self.binding = callback

    def add_init_script(self, script: str):
        self.init_script = script

    def evaluate(self, script: str):
        self.evaluated_script = script


def test_captures_fetch_stream_chunks(tmp_path: Path):
    output_folder = tmp_path / "debug"
    collector = DevtoolsUser(
        cast(Page, FakePage()), output_folder, policy=DevtoolsLogPolicy.from_any(policy_mode="all")
    )
    network_folder = output_folder / "network"
    network_folder.mkdir()

    collector._start_fetch_stream_capture()
    collector._start_fetch_stream_capture()
    page = cast(FakePage, collector.page)
    init_script = page.init_script
    binding = page.binding
    assert init_script is not None
    assert init_script == page.evaluated_script
    assert "response.clone()" in init_script
    assert binding is not None
    binding(
        {},
        {
            "stream_id": "fetch-1",
            "event_type": "chunk",
            "url": "https://example.com/chat",
            "method": "POST",
            "status": 200,
            "content_type": "text/event-stream",
            "chunk_index": 0,
            "timestamp_ms": 1234.5,
            "elapsed_ms": 12.5,
            "data": "data: hello\\n\\n",
        },
    )

    event_path = network_folder / "fetch_stream.jsonl"
    events = [FetchStreamEvent.model_validate_json(line) for line in event_path.read_text().splitlines()]
    assert len(events) == 1
    assert events[0].event_type == "chunk"
    assert events[0].data == "data: hello\\n\\n"


def test_default_policy_skips_fetch_stream_capture(tmp_path: Path):
    output_folder = tmp_path / "default-policy"
    collector = DevtoolsUser(cast(Page, FakePage()), output_folder)
    collector._start_network(FakeCDPClient())
    collector._on_fetch_stream_event(
        {},
        {
            "stream_id": "fetch-1",
            "event_type": "chunk",
            "url": "https://example.com/stream",
            "method": "GET",
            "status": 200,
            "chunk_index": 0,
            "timestamp_ms": 1000,
            "elapsed_ms": 10,
            "data": "ignored",
        },
    )

    assert not (output_folder / "network" / "fetch_stream.jsonl").exists()


def test_collects_event_stream_messages(tmp_path: Path):

    output_folder = tmp_path / "debug"
    collector = DevtoolsUser(cast(Page, object()), output_folder)
    client = FakeCDPClient()
    collector._start_network(client)
    assert "Network.eventSourceMessageReceived" in client.handlers_when_enabled

    client.emit(
        "Network.requestWillBeSent",
        {
            "requestId": "sse-1",
            "request": {
                "method": "GET",
                "url": "https://example.com/events",
            },
        },
    )
    client.emit(
        "Network.eventSourceMessageReceived",
        {
            "requestId": "sse-1",
            "timestamp": 123.5,
            "eventName": "message",
            "eventId": "42",
            "data": "hello",
        },
    )

    event_path = output_folder / "network" / "event_stream.jsonl"
    event = ServerSentEvent.model_validate_json(event_path.read_text().strip())
    assert event.request_id == "sse-1"
    assert event.url == "https://example.com/events"
    assert event.data == "hello"
    assert event.event_id == "42"


def test_http_transaction_policy_filters_saved_logs(tmp_path: Path):
    output_folder = tmp_path / "filtered-http"
    collector = DevtoolsUser(
        cast(Page, object()),
        output_folder,
        policy=DevtoolsLogPolicy.from_any(
            transaction_predicates=lambda transaction: "/keep" in transaction.request.url
        ),
    )
    client = FakeCDPClient()
    collector._start_network(client)

    for request_id, path in (("keep", "keep"), ("drop", "drop")):
        client.emit(
            "Network.requestWillBeSent",
            {
                "requestId": request_id,
                "request": {"method": "GET", "url": f"https://example.com/{path}"},
            },
        )
        client.emit(
            "Network.responseReceived",
            {"requestId": request_id, "response": {"status": 200, "headers": {}}},
        )
        client.emit("Network.loadingFinished", {"requestId": request_id})

    saved_logs = list((output_folder / "network").glob("*.json"))
    assert [path.stem for path in saved_logs] == ["keep"]


def test_websocket_policy_filters_connections(tmp_path: Path):
    output_folder = tmp_path / "filtered-websocket"
    collector = DevtoolsUser(
        cast(Page, object()),
        output_folder,
        policy=DevtoolsLogPolicy.from_any(
            websocket_connection_predicates=lambda connection: any(
                event.event_type == "frame_received" for event in connection.events
            )
        ),
    )
    client = FakeCDPClient()
    collector._start_network(client)
    client.emit("Network.webSocketCreated", {"requestId": "ws-1", "url": "wss://example.com/chat"})
    client.emit(
        "Network.webSocketFrameReceived",
        {"requestId": "ws-1", "response": {"opcode": 1, "mask": False, "payloadData": "hello"}},
    )
    client.emit("Network.webSocketClosed", {"requestId": "ws-1"})

    event_path = output_folder / "network" / "websocket.jsonl"
    events = [WebSocketEvent.model_validate_json(line) for line in event_path.read_text().splitlines()]
    assert [event.event_type for event in events] == ["created", "frame_received", "closed"]


def test_server_sent_events_policy_filters_event_streams(tmp_path: Path):
    output_folder = tmp_path / "filtered-sse"
    collector = DevtoolsUser(
        cast(Page, object()),
        output_folder,
        policy=DevtoolsLogPolicy.from_any(
            server_sent_events_predicates=lambda events: any(
                event.event_name == "important" for event in events.events
            )
        ),
    )
    client = FakeCDPClient()
    collector._start_network(client)
    client.emit(
        "Network.requestWillBeSent",
        {"requestId": "sse-1", "request": {"method": "GET", "url": "https://example.com/events"}},
    )
    client.emit(
        "Network.eventSourceMessageReceived",
        {"requestId": "sse-1", "timestamp": 1.0, "eventName": "ignore", "data": "no"},
    )
    client.emit(
        "Network.eventSourceMessageReceived",
        {"requestId": "sse-1", "timestamp": 2.0, "eventName": "important", "data": "yes"},
    )

    event_path = output_folder / "network" / "event_stream.jsonl"
    events = [ServerSentEvent.model_validate_json(line) for line in event_path.read_text().splitlines()]
    assert [event.data for event in events] == ["no", "yes"]


def test_collects_websocket_lifecycle_and_frames(tmp_path: Path):


    output_folder = tmp_path / "debug"
    collector = DevtoolsUser(cast(Page, object()), output_folder)
    client = FakeCDPClient()
    collector._start_network(client)
    assert "Network.webSocketFrameReceived" in client.handlers_when_enabled

    client.emit(
        "Network.webSocketCreated",
        {"requestId": "ws-1", "url": "wss://example.com/chat"},
    )
    client.emit(
        "Network.webSocketFrameReceived",
        {
            "requestId": "ws-1",
            "timestamp": 123.5,
            "response": {"opcode": 1, "mask": False, "payloadData": "hello"},
        },
    )
    client.emit("Network.webSocketClosed", {"requestId": "ws-1"})

    event_path = output_folder / "network" / "websocket.jsonl"
    events = [WebSocketEvent.model_validate_json(line) for line in event_path.read_text().splitlines()]
    assert [event.event_type for event in events] == [
        "created",
        "frame_received",
        "closed",
    ]
    assert events[1].url == "wss://example.com/chat"
    assert events[1].frame is not None
    assert events[1].frame.payload_data == "hello"
    assert events[1].frame.opcode == 1
