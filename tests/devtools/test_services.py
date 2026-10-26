import hashlib
import json
import logging
from collections.abc import Callable
from pathlib import Path
from threading import Event as ThreadingEvent
from threading import RLock
from typing import cast

import pytest
from playwright.sync_api import BrowserContext, Page

from fairybrowser.devtools import DevtoolsLogPolicy, DevtoolsService
from fairybrowser.devtools.infra.cdp.connection import _CDPCommandError, _CDPCommandResponse, _FlatCDPConnection
from fairybrowser.devtools.models.fetch_text_stream_event import FetchTextStreamEvent
from fairybrowser.devtools.models.http_transaction import HTTPTransaction
from fairybrowser.devtools.models.server_sent_events import ServerSentEvent
from fairybrowser.devtools.models.websockets import WebsocketEvent


class FakeCDPClient:
    def __init__(self):
        self.handlers: dict[str, Callable[[dict], None]] = {}
        self.handlers_when_enabled: set[str] = set()
        self.detach_count = 0

    def send(self, method: str, params: dict | None = None):
        self.last_send = (method, params)
        if method == "Target.getTargetInfo":
            return {"targetInfo": {"targetId": "page-target"}}
        if method == "Network.enable":
            self.handlers_when_enabled = set(self.handlers)
        return {}

    def on(self, event_name: str, handler: Callable[[dict], None]):
        self.handlers[event_name] = handler

    def emit(self, event_name: str, params: dict):
        self.handlers[event_name](params)

    def detach(self):
        self.detach_count += 1


class FakeFlatCDPConnection:
    def __init__(self, target_infos: list[dict] | None = None):
        self.target_infos = target_infos or []
        self.handlers: dict[tuple[str | None, str], Callable[[dict], None]] = {}
        self.commands: list[tuple[int, str, dict | None, str | None]] = []
        self.pending: dict[int, tuple[str | None, Callable[[_CDPCommandResponse], None]]] = {}
        self.next_command_id = 0
        self.supports_auto_attach = True
        self.closed = False

    def on(self, event_name: str, handler: Callable[[dict], None], session_id: str | None = None):
        self.handlers[(session_id, event_name)] = handler

    def send(self, method: str, params: dict | None = None, session_id: str | None = None, timeout: float = 10):
        self.next_command_id += 1
        self.commands.append((self.next_command_id, method, params, session_id))
        if method == "Target.autoAttachRelated" and not self.supports_auto_attach:
            raise RuntimeError("Target.autoAttachRelated is unavailable")
        if method == "Target.getTargets":
            return {"targetInfos": self.target_infos}
        return {}

    def send_async(
        self,
        method: str,
        params: dict | None,
        callback: Callable[[_CDPCommandResponse], None],
        session_id: str | None = None,
    ):
        self.next_command_id += 1
        command_id = self.next_command_id
        self.commands.append((command_id, method, params, session_id))
        if method == "Target.attachToTarget":
            callback(_CDPCommandResponse(result={"sessionId": f"session-{params['targetId']}"}))
        elif method == "Network.getResponseBody":
            self.pending[command_id] = (session_id, callback)
        else:
            callback(_CDPCommandResponse(result={}))

    def emit(self, event_name: str, params: dict, session_id: str | None = None):
        self.handlers[(session_id, event_name)](params)

    def respond(self, command_id: int, result: dict):
        _, callback = self.pending.pop(command_id)
        callback(_CDPCommandResponse(result=result))

    def respond_error(self, command_id: int, message: str):
        _, callback = self.pending.pop(command_id)
        callback(_CDPCommandResponse(error=RuntimeError(message)))

    def cancel_session(self, session_id: str):
        for command_id, (pending_session_id, callback) in tuple(self.pending.items()):
            if pending_session_id == session_id:
                self.pending.pop(command_id)
                callback(_CDPCommandResponse(error=ConnectionError("target detached")))

    def close(self):
        self.closed = True


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


def test_async_cdp_response_distinguishes_command_errors_from_results():
    connection = object.__new__(_FlatCDPConnection)
    connection._lock = RLock()
    responses: list[_CDPCommandResponse] = []
    connection._sync_pending = {}
    connection._async_pending = {
        1: (None, "Runtime.enable", responses.append),
        2: (None, "Network.getResponseBody", responses.append),
    }

    connection._dispatch({"id": 1, "result": {}})
    connection._dispatch({"id": 2, "error": {"code": -32000, "message": "Body unavailable"}})

    assert responses[0].result == {}
    assert responses[0].error is None
    assert responses[1].result is None
    assert isinstance(responses[1].error, _CDPCommandError)
    assert responses[1].error.code == -32000
    assert str(responses[1].error) == "Body unavailable"


def test_requires_output_folder_or_memory_storage():
    with pytest.raises(ValueError):
        DevtoolsService(cast(Page, object()), save_memory=False)


def test_default_setting_passed():
    DevtoolsService(cast(Page, object()))


def test_custom_logger_is_passed_to_network_capturer():
    logger = logging.getLogger("test.devtools")
    service = DevtoolsService(cast(Page, object()), logger=logger)

    assert service._logger is logger
    assert service._network_event_capturer._logger is logger


def test_terminate_detaches_cdp_session(monkeypatch: pytest.MonkeyPatch):
    client = FakeCDPClient()

    class FakeContext:
        def new_cdp_session(self, _page):
            return client

    context = cast(BrowserContext, FakeContext())
    collector = DevtoolsService(
        cast(Page, object()),
        policy=DevtoolsLogPolicy.from_any(categories=[]),
        save_memory=True,
    )
    monkeypatch.setattr(collector, "_to_context", lambda _page: context)
    monkeypatch.setattr(collector, "_start_network", lambda _client: None)
    monkeypatch.setattr(collector._event_publisher, "start", lambda: None)

    collector.start()
    collector.terminate()
    collector.terminate()

    assert client.detach_count == 1


def test_selected_targets_capture_enabled_categories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    page_client = FakeCDPClient()
    flat_client = FakeFlatCDPConnection()
    received_loggers = []

    def create_flat_connection(_url, logger=None):
        received_loggers.append(logger)
        return flat_client

    monkeypatch.setattr("fairybrowser.devtools.services._FlatCDPConnection", create_flat_connection)

    class FakeContext:
        browser = None

        def new_cdp_session(self, _page):
            return page_client

    fake_page = FakePage()
    collector = DevtoolsService(
        cast(Page, fake_page),
        tmp_path / "service-worker",
        policy=DevtoolsLogPolicy.from_any(categories=["http", "event_source", "websocket", "console", "fetch_stream"]),
        target_types=("page", "service_worker"),
        browser_cdp_endpoint="ws://cdp.test/devtools/browser/fake",
    )
    monkeypatch.setattr(collector, "_to_context", lambda _page: FakeContext())

    collector.start()
    try:
        assert received_loggers == [collector._logger]
        auto_attach = next(
            params for _, method, params, _ in flat_client.commands if method == "Target.autoAttachRelated"
        )
        assert auto_attach == {
            "targetId": "page-target",
            "waitForDebuggerOnStart": True,
            "filter": [{"type": "service_worker"}],
        }

        def attach_worker(target_id: str, session_id: str):
            flat_client.emit(
                "Target.attachedToTarget",
                {
                    "sessionId": session_id,
                    "targetInfo": {"targetId": target_id, "type": "service_worker"},
                    "waitingForDebugger": True,
                },
            )

        attach_worker("worker-existing", "session-worker-existing")
        attach_worker("worker-new", "session-worker-new")
        assert collector._service_worker_target_ids == {"worker-existing", "worker-new"}
        worker_commands = [(method, session_id) for _, method, _, session_id in flat_client.commands]
        assert {method for method, session_id in worker_commands if session_id == "session-worker-existing"} >= {
            "Network.enable",
            "Runtime.enable",
            "Runtime.runIfWaitingForDebugger",
        }

        def emit_worker(method: str, params: dict):
            flat_client.emit(method, params, session_id="session-worker-existing")

        emit_worker(
            "Network.requestWillBeSent",
            {"requestId": "http-1", "request": {"method": "POST", "url": "https://example.com/api"}},
        )
        emit_worker(
            "Network.responseReceived",
            {"requestId": "http-1", "response": {"status": 200, "headers": {"content-type": "text/plain"}}},
        )
        emit_worker("Network.loadingFinished", {"requestId": "http-1"})
        get_body_command_id = next(
            command_id for command_id, method, _, _ in flat_client.commands if method == "Network.getResponseBody"
        )
        flat_client.respond(get_body_command_id, {"body": "reply", "base64Encoded": False})

        emit_worker(
            "Network.requestWillBeSent",
            {"requestId": "sse-1", "request": {"method": "GET", "url": "https://example.com/events"}},
        )
        emit_worker(
            "Network.eventSourceMessageReceived",
            {"requestId": "sse-1", "timestamp": 1.0, "eventName": "message", "data": "hello"},
        )
        emit_worker("Network.webSocketCreated", {"requestId": "ws-1", "url": "wss://example.com/chat"})
        emit_worker(
            "Network.webSocketFrameReceived",
            {"requestId": "ws-1", "response": {"opcode": 1, "mask": False, "payloadData": "hello"}},
        )
        emit_worker("Runtime.consoleAPICalled", {"type": "log", "args": [{"value": "worker log"}]})
    finally:
        collector.terminate()

    assert page_client.detach_count == 1
    assert flat_client.closed
    assert "worker log" in capsys.readouterr().out
    assert fake_page.init_script is not None
    assert collector.network_log is not None
    transaction = collector.network_log.http_transactions[0]
    assert transaction.request.url == "https://example.com/api"
    assert transaction.response is not None
    assert transaction.response.body == b"reply"
    assert collector.network_log.server_sent_events[0].events[0].data == "hello"
    connection = collector.network_log.websocket_connections[0]
    assert connection.request_id == "service-worker:worker-existing:ws-1"
    assert [event.event_type for event in connection.events] == ["created", "frame_received"]
    assert connection.events[1].frame is not None
    assert connection.events[1].frame.payload_data == "hello"


def test_failed_service_worker_setup_resumes_and_detaches_session(monkeypatch: pytest.MonkeyPatch):
    page_client = FakeCDPClient()
    flat_client = FakeFlatCDPConnection()
    monkeypatch.setattr("fairybrowser.devtools.services._FlatCDPConnection", lambda _url, _logger=None: flat_client)

    class FakeContext:
        browser = None

        def new_cdp_session(self, _page):
            return page_client

    collector = DevtoolsService(
        cast(Page, object()),
        policy=DevtoolsLogPolicy.from_any(categories=["websocket"]),
        target_types=("service_worker",),
        browser_cdp_endpoint="ws://cdp.test/devtools/browser/fake",
    )
    monkeypatch.setattr(collector, "_to_context", lambda _page: FakeContext())

    def fail_network(*_args, **_kwargs):
        raise RuntimeError("Network setup failed")

    monkeypatch.setattr(collector, "_start_network", fail_network)

    collector.start()
    try:
        with pytest.raises(RuntimeError, match="Network setup failed"):
            flat_client.emit(
                "Target.attachedToTarget",
                {
                    "sessionId": "worker-session",
                    "targetInfo": {"targetId": "worker-1", "type": "service_worker"},
                    "waitingForDebugger": True,
                },
            )
    finally:
        collector.terminate()

    commands = [(method, params, session_id) for _, method, params, session_id in flat_client.commands]
    resume_index = commands.index(("Runtime.runIfWaitingForDebugger", {}, "worker-session"))
    detach_index = next(
        index
        for index, (method, params, session_id) in enumerate(commands)
        if method == "Target.detachFromTarget" and params == {"sessionId": "worker-session"} and session_id is None
    )
    assert resume_index < detach_index
    assert "worker-1" not in collector._service_worker_target_ids
    assert "worker-session" not in collector._service_worker_sessions


def test_service_worker_target_discovery_falls_back_without_auto_attach(monkeypatch: pytest.MonkeyPatch):
    flat_client = FakeFlatCDPConnection(
        [{"targetId": "worker-1", "type": "service_worker", "url": "https://example.com/sw.js"}]
    )
    flat_client.supports_auto_attach = False
    page_client = FakeCDPClient()
    monkeypatch.setattr("fairybrowser.devtools.services._FlatCDPConnection", lambda _url, _logger=None: flat_client)

    class FakeContext:
        browser = None

        def new_cdp_session(self, _page):
            return page_client

    fake_page = FakePage()
    collector = DevtoolsService(
        cast(Page, fake_page),
        policy=DevtoolsLogPolicy.from_any(categories=["websocket", "fetch_stream"]),
        target_types=("service_worker",),
        browser_cdp_endpoint="ws://cdp.test/devtools/browser/fake",
    )
    monkeypatch.setattr(collector, "_to_context", lambda _page: FakeContext())

    collector.start()
    try:
        assert any(method == "Target.setDiscoverTargets" for _, method, _, _ in flat_client.commands)
        flat_client.emit(
            "Network.webSocketCreated",
            {"requestId": "ws-1", "url": "wss://example.com/chat"},
            session_id="session-worker-1",
        )
    finally:
        collector.terminate()

    assert collector.network_log is not None
    assert collector.network_log.websocket_connections[0].events[0].url == "wss://example.com/chat"
    assert fake_page.init_script is None


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
    collector.on_fetch_stream_event.subscribe(lambda event: (captured_events.append(event), received_event.set()))

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
    page = FakePage()
    collector = DevtoolsService(
        cast(Page, page),
        output_folder,
        policy=DevtoolsLogPolicy.from_any(
            categories=["fetch_stream"],
            fetch_stream_event_predicates=lambda event: event.event_type == "chunk",
        ),
        save_memory=True,
    )
    (output_folder / "network").mkdir()
    collector._start_fetch_stream_capture()
    assert page.binding is not None
    page.binding(
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
    page = FakePage()
    collector = DevtoolsService(cast(Page, page), output_folder)
    collector._start_network(FakeCDPClient())
    collector._start_fetch_stream_capture()
    assert page.binding is not None
    page.binding(
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
    collector.on_server_sent_event.subscribe(lambda event: (captured_events.append(event), received_event.set()))
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
        "Network.webSocketHandshakeResponseReceived",
        {"requestId": "ws-1", "response": {"status": 101, "headers": {"upgrade": "websocket"}}},
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
        "handshake_response",
        "frame_received",
        "closed",
    ]
    assert events[1].frame is None
    assert events[1].params["response"]["status"] == 101
    assert events[2].url == "wss://example.com/chat"
    assert events[2].frame is not None
    assert events[2].frame.payload_data == "hello"
    assert events[2].frame.opcode == 1
