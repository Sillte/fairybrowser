import json
from pathlib import Path

from pydantic import BaseModel

from fairybrowser.devtools import NetworkLog
from fairybrowser.devtools.models.fetch_text_stream_event import FetchTextStreamEvent
from fairybrowser.devtools.models.http_transaction import HTTPRequest, HTTPResponse, HTTPTransaction
from fairybrowser.devtools.models.server_sent_events import ServerSentEvent
from fairybrowser.devtools.models.websockets import WebsocketEvent, WebsocketFrame


def _write_jsonl(path: Path, events: list[BaseModel]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"{event.model_dump_json()}\n" for event in events), encoding="utf-8")


def test_network_log_loads_and_groups_saved_logs(tmp_path: Path):
    network_folder = tmp_path / "network"
    network_folder.mkdir()

    transaction = HTTPTransaction(
        request=HTTPRequest(url="https://example.com/api", method="POST", body=b'{"value": 1}'),
        response=HTTPResponse(status=200, body=b'{"ok": true}'),
    )
    (tmp_path / "request.json").write_text(json.dumps([transaction.model_dump(mode="json")]), encoding="utf-8")
    nested_transaction = HTTPTransaction(request=HTTPRequest(url="https://example.com/next", method="GET"))
    (network_folder / "nested.json").write_text(
        json.dumps([nested_transaction.model_dump(mode="json")]), encoding="utf-8"
    )

    _write_jsonl(
        network_folder / "event_stream" / "sse-1-hash.jsonl",
        [
            ServerSentEvent(request_id="sse-1", timestamp=1.0, data="one"),
            ServerSentEvent(request_id="sse-1", timestamp=2.0, data="two"),
        ],
    )
    _write_jsonl(
        network_folder / "event_stream" / "sse-2-hash.jsonl",
        [ServerSentEvent(request_id="sse-2", timestamp=3.0, data="three")],
    )
    _write_jsonl(
        network_folder / "fetch_stream.jsonl",
        [
            FetchTextStreamEvent(
                stream_id="fetch-1",
                event_type="chunk",
                url="https://example.com/stream",
                method="GET",
                status=200,
                chunk_index=0,
                timestamp_ms=1000,
                elapsed_ms=5,
                text="chunk",
            )
        ],
    )
    _write_jsonl(
        network_folder / "websocket" / "ws-1-hash.jsonl",
        [
            WebsocketEvent(request_id="ws-1", event_type="created", url="wss://example.com/chat"),
            WebsocketEvent(
                request_id="ws-1",
                event_type="frame_received",
                frame=WebsocketFrame(opcode=1, mask=False, payload_data="hello"),
            ),
        ],
    )
    log = NetworkLog.load(tmp_path)
    snapshot = log.snapshot()

    assert len(snapshot.http_transactions) == 2
    assert len(log.get_http_transactions(method="POST")) == 1
    assert len(log.get_http_transactions(path="/API")) == 1
    api_transaction = next(
        transaction for transaction in snapshot.http_transactions if transaction.request.url.endswith("/api")
    )
    assert api_transaction.request.body_json == {"value": 1}
    assert [stream.request_id for stream in snapshot.server_sent_events] == ["sse-1", "sse-2"]
    assert [event.data for event in snapshot.server_sent_events[0].events] == ["one", "two"]
    assert len(snapshot.fetch_stream_events) == 1
    assert len(snapshot.websocket_connections) == 1
    connection = snapshot.websocket_connections[0]
    assert connection.events[1].frame is not None
    assert connection.events[1].frame.payload_data == "hello"


def test_network_log_handles_missing_optional_logs(tmp_path: Path):
    snapshot = NetworkLog.load(tmp_path).snapshot()

    assert snapshot.http_transactions == ()
    assert snapshot.server_sent_events == ()
    assert snapshot.fetch_stream_events == ()
    assert snapshot.websocket_connections == ()
