import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from threading import Event as ThreadingEvent
from typing import cast

import pytest
from playwright.sync_api import Page

from fairybrowser.devtools import DevtoolsLogPolicy, DevtoolsService
from fairybrowser.devtools.models.fetch_text_stream_event import FetchTextStreamEvent
from fairybrowser.devtools.models.http_transaction import HTTPTransaction
from fairybrowser.devtools.models.server_sent_events import ServerSentEvent
from fairybrowser.devtools.models.websockets import WebsocketEvent


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


def test_requires_output_folder_or_memory_storage():
    with pytest.raises(ValueError, match="output_folder or set save_memory=True"):
        DevtoolsService(cast(Page, object()))


def test_explicit_output_folder_is_initialized(tmp_path: Path):
    output_folder = tmp_path / "existing"
    output_folder.mkdir()
    (output_folder / "stale.log").write_text("stale", encoding="utf-8")

    collector = DevtoolsService(cast(Page, object()), output_folder)

    assert collector.output_folder == output_folder
    assert not (output_folder / "stale.log").exists()


def test_memory_only_mode_updates_network_log_and_keeps_snapshots_immutable():
    collector = DevtoolsService(cast(Page, object()), save_memory=True)
    client = FakeCDPClient()
    collector._start_network(client)
    client.emit(
        "Network.requestWillBeSent",
        {"requestId": "sse-1", "request": {"method": "GET", "url": "https://example.com/events"}},
    )
    client.emit(
        "Network.eventSourceMessageReceived",
        {"requestId": "sse-1", "timestamp": 1.0, "eventName": "message", "data": "one"},
    )

    assert collector.network_log is not None
    first_snapshot = collector.network_log.snapshot()
    client.emit(
        "Network.eventSourceMessageReceived",
        {"requestId": "sse-1", "timestamp": 2.0, "eventName": "message", "data": "two"},
    )
    latest_snapshot = collector.network_log.snapshot()

    assert [event.data for event in first_snapshot.server_sent_events[0].events] == ["one"]
    assert [event.data for event in latest_snapshot.server_sent_events[0].events] == ["one", "two"]
    assert collector.output_folder is None


def test_memory_and_file_storage_can_be_enabled_together(tmp_path: Path):
    output_folder = tmp_path / "both-modes"
    collector = DevtoolsService(cast(Page, object()), output_folder, save_memory=True)
    captured_transactions = []
    received_transaction = ThreadingEvent()
    collector.on_http_transaction.subscribe(
        lambda transaction: (captured_transactions.append(transaction), received_transaction.set())
    )
    collector._event_publisher.start()
    client = FakeCDPClient()
    collector._start_network(client)
    client.emit(
        "Network.requestWillBeSent",
        {"requestId": "http-1", "request": {"method": "GET", "url": "https://example.com"}},
    )
    client.emit(
        "Network.responseReceived",
        {"requestId": "http-1", "response": {"status": 200, "headers": {}}},
    )
    client.emit("Network.loadingFinished", {"requestId": "http-1"})
    try:
        assert received_transaction.wait(2)
    finally:
        collector.terminate()

    assert collector.network_log is not None
    assert len(collector.network_log.http_transactions) == 1
    assert (output_folder / "network" / "http-1.json").exists()
    assert len(captured_transactions) == 1
    assert captured_transactions[0] == collector.network_log.http_transactions[0]


def test_captures_fetch_stream_chunks(tmp_path: Path):
    output_folder = tmp_path / "debug"
    collector = DevtoolsService(
        cast(Page, FakePage()), output_folder, policy=DevtoolsLogPolicy.from_any(policy_mode="all")
    )
    network_folder = output_folder / "network"
    network_folder.mkdir()
    captured_events = []
    received_event = ThreadingEvent()
    collector.on_fetch_stream_event.subscribe(
        lambda event: (captured_events.append(event), received_event.set())
    )

    collector._start_fetch_stream_capture()
    collector._start_fetch_stream_capture()
    page = cast(FakePage, collector.page)
    init_script = page.init_script
    binding = page.binding
    assert init_script is not None
    assert init_script == page.evaluated_script
    assert "response.clone()" in init_script
    assert binding is not None
    collector._event_publisher.start()
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
            "text": "data: hello\\n\\n",
        },
    )
    try:
        assert received_event.wait(2)
    finally:
        collector.terminate()

    event_path = network_folder / "fetch_stream.jsonl"
    events = [FetchTextStreamEvent.model_validate_json(line) for line in event_path.read_text().splitlines()]
    assert len(events) == 1
    assert events[0].event_type == "chunk"
    assert events[0].text == "data: hello\\n\\n"
    assert captured_events == events


def test_fetch_stream_event_predicate_filters_capture(tmp_path: Path):
    output_folder = tmp_path / "filtered-fetch-stream"
    collector = DevtoolsService(
        cast(Page, FakePage()),
        output_folder,
        policy=DevtoolsLogPolicy.from_any(
            categories=["fetch_stream"],
            fetch_stream_event_predicates=lambda event: event.event_type == "chunk",
        ),
        save_memory=True,
    )
    (output_folder / "network").mkdir()
    collector._on_fetch_stream_event(
        {},
        {
            "stream_id": "fetch-1",
            "event_type": "complete",
            "url": "https://example.com/stream",
            "method": "GET",
            "status": 200,
            "chunk_index": 0,
            "timestamp_ms": 1000,
            "elapsed_ms": 10,
        },
    )

    assert collector.network_log is not None
    assert collector.network_log.fetch_stream_events == []
    assert not (output_folder / "network" / "fetch_stream.jsonl").exists()


def test_default_policy_skips_fetch_stream_capture(tmp_path: Path):
    output_folder = tmp_path / "default-policy"
    collector = DevtoolsService(cast(Page, FakePage()), output_folder)
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
    collector = DevtoolsService(cast(Page, object()), output_folder)
    captured_events = []
    received_event = ThreadingEvent()
    collector.on_server_sent_event.subscribe(
        lambda event: (captured_events.append(event), received_event.set())
    )
    client = FakeCDPClient()
    collector._start_network(client)
    assert "Network.eventSourceMessageReceived" in client.handlers_when_enabled

    collector._event_publisher.start()
    client.emit(
        "Network.requestWillBeSent",
        {
            "requestId": "sse/1",
            "request": {
                "method": "GET",
                "url": "https://example.com/events",
            },
        },
    )
    client.emit(
        "Network.eventSourceMessageReceived",
        {
            "requestId": "sse/1",
            "timestamp": 123.5,
            "eventName": "message",
            "eventId": "42",
            "data": "hello",
        },
    )
    try:
        assert received_event.wait(2)
    finally:
        collector.terminate()

    event_paths = list((output_folder / "network" / "event_stream").glob("*.jsonl"))
    assert len(event_paths) == 1
    assert "sse_1" in event_paths[0].stem
    assert hashlib.sha256(b"sse/1").hexdigest() in event_paths[0].stem
    assert len(captured_events) == 1
    assert captured_events[0].data == "hello"
    event = ServerSentEvent.model_validate_json(event_paths[0].read_text().strip())
    assert event.request_id == "sse/1"
    assert event.url == "https://example.com/events"
    assert event.data == "hello"
    assert event.event_id == "42"


def test_http_transaction_policy_filters_saved_logs(tmp_path: Path):
    output_folder = tmp_path / "filtered-http"
    collector = DevtoolsService(
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
    saved_data = json.loads(saved_logs[0].read_text(encoding="utf-8"))
    assert "request" in saved_data[0]
    assert "url" not in saved_data[0]
    transaction = HTTPTransaction.model_validate(saved_data[0])
    assert transaction.request.url == "https://example.com/keep"


def test_websocket_policy_filters_connections(tmp_path: Path):
    output_folder = tmp_path / "filtered-websocket"
    collector = DevtoolsService(
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

    event_paths = list((output_folder / "network" / "websocket").glob("*.jsonl"))
    assert len(event_paths) == 1
    events = [WebsocketEvent.model_validate_json(line) for line in event_paths[0].read_text().splitlines()]
    assert [event.event_type for event in events] == ["created", "frame_received", "closed"]


def test_server_sent_events_policy_filters_event_streams(tmp_path: Path):
    output_folder = tmp_path / "filtered-sse"
    collector = DevtoolsService(
        cast(Page, object()),
        output_folder,
        policy=DevtoolsLogPolicy.from_any(
            server_sent_events_predicates=lambda events: any(event.event_name == "important" for event in events.events)
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

    event_paths = list((output_folder / "network" / "event_stream").glob("*.jsonl"))
    assert len(event_paths) == 1
    events = [ServerSentEvent.model_validate_json(line) for line in event_paths[0].read_text().splitlines()]
    assert [event.data for event in events] == ["no", "yes"]


def test_collects_websocket_lifecycle_and_frames(tmp_path: Path):
    output_folder = tmp_path / "debug"
    collector = DevtoolsService(cast(Page, object()), output_folder)
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

    event_paths = list((output_folder / "network" / "websocket").glob("*.jsonl"))
    assert len(event_paths) == 1
    events = [WebsocketEvent.model_validate_json(line) for line in event_paths[0].read_text().splitlines()]
    assert [event.event_type for event in events] == [
        "created",
        "frame_received",
        "closed",
    ]
    assert events[1].url == "wss://example.com/chat"
    assert events[1].frame is not None
    assert events[1].frame.payload_data == "hello"
    assert events[1].frame.opcode == 1
