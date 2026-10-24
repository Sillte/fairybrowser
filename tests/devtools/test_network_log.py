import json
from pathlib import Path

from pydantic import BaseModel

from fairybrowser.devtools.models import FetchStreamEvent
from fairybrowser.devtools.models.http_transaction import RawCommunicationInfo
from fairybrowser.devtools.models.network_log import NetworkLog
from fairybrowser.devtools.models.server_sent_events import ServerSentEvent
from fairybrowser.devtools.models.websockets import WebSocketEvent, WebSocketFrame


def _write_jsonl(path: Path, events: list[BaseModel]) -> None:
    path.write_text("".join(f"{event.model_dump_json()}\n" for event in events), encoding="utf-8")


def test_network_log_loads_and_groups_saved_logs(tmp_path: Path):
    network_folder = tmp_path / "network"
    network_folder.mkdir()

    raw = RawCommunicationInfo(
        status=200,
        url="https://example.com/api",
        method="POST",
        request_body=b'{"value": 1}',
        response_body=b'{"ok": true}',
    )
    (tmp_path / "request.json").write_text(
        json.dumps([raw.model_dump(mode="json")]), encoding="utf-8"
    )
    nested_raw = RawCommunicationInfo(url="https://example.com/next", method="GET")
    (network_folder / "nested.json").write_text(
        json.dumps([nested_raw.model_dump(mode="json")]), encoding="utf-8"
    )

    _write_jsonl(
        network_folder / "event_stream.jsonl",
        [
            ServerSentEvent(request_id="sse-1", timestamp=1.0, data="one"),
            ServerSentEvent(request_id="sse-1", timestamp=2.0, data="two"),
            ServerSentEvent(request_id="sse-2", timestamp=3.0, data="three"),
        ],
    )
    _write_jsonl(
        network_folder / "fetch_stream.jsonl",
        [
            FetchStreamEvent(
                stream_id="fetch-1",
                event_type="chunk",
                url="https://example.com/stream",
                method="GET",
                status=200,
                chunk_index=0,
                timestamp_ms=1000,
                elapsed_ms=5,
                data="chunk",
            )
        ],
    )
    _write_jsonl(
        network_folder / "websocket.jsonl",
        [
            WebSocketEvent(request_id="ws-1", event_type="created", url="wss://example.com/chat"),
            WebSocketEvent(
                request_id="ws-1",
                event_type="frame_received",
                frame=WebSocketFrame(opcode=1, mask=False, payload_data="hello"),
            ),
        ],
    )

    log = NetworkLog.load(tmp_path)

    assert len(log.http_transactions) == 2
    api_transaction = next(
        transaction for transaction in log.http_transactions if transaction.request.url.endswith("/api")
    )
    assert api_transaction.request.body_json == {"value": 1}
    assert [stream.request_id for stream in log.server_sent_events] == ["sse-1", "sse-2"]
    assert [event.data for event in log.server_sent_events[0].events] == ["one", "two"]
    assert len(log.fetch_stream_events) == 1
    assert len(log.websocket_connections) == 1
    assert log.websocket_connections[0].request_id == "ws-1"
    assert log.websocket_connections[0].events[1].frame is not None
    assert log.websocket_connections[0].events[1].frame.payload_data == "hello"


def test_network_log_handles_missing_optional_logs(tmp_path: Path):
    log = NetworkLog.load(tmp_path)

    assert log.http_transactions == ()
    assert log.server_sent_events == ()
    assert log.fetch_stream_events == ()
    assert log.websocket_connections == ()
