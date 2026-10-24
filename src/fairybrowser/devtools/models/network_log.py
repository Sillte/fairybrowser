import json
from collections import defaultdict
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from fairybrowser.devtools.models import FetchStreamEvent
from fairybrowser.devtools.models.http_transaction import HTTPTransaction, RawCommunicationInfo
from fairybrowser.devtools.models.server_sent_events import ServerSentEvent, ServerSentEvents
from fairybrowser.devtools.models.websockets import WebSocketConnection, WebSocketEvent


class NetworkLog(BaseModel, frozen=True):
    http_transactions: tuple[HTTPTransaction, ...] = ()
    server_sent_events: tuple[ServerSentEvents, ...] = ()
    fetch_stream_events: tuple[FetchStreamEvent, ...] = ()
    websocket_connections: tuple[WebSocketConnection, ...] = ()

    @classmethod
    def load(cls, log_folder: str | Path) -> "NetworkLog":
        folder = Path(log_folder)
        if not folder.is_dir():
            raise FileNotFoundError(f"Network log folder does not exist: {folder}")

        raw_infos: list[RawCommunicationInfo] = []
        for path in sorted((*folder.glob("*.json"), *folder.glob("network/*.json"))):
            data = json.loads(path.read_text(encoding="utf-8"))
            entries = data if isinstance(data, list) else [data]
            raw_infos.extend(RawCommunicationInfo.model_validate(entry) for entry in entries)

        transactions = tuple(HTTPTransaction.from_raw(info) for info in raw_infos)
        sse_by_request: dict[str, list[ServerSentEvent]] = defaultdict(list)
        for event in _read_jsonl(folder / "network" / "event_stream.jsonl", ServerSentEvent):
            sse_by_request[event.request_id].append(event)

        fetch_events = tuple(
            _read_jsonl(folder / "network" / "fetch_stream.jsonl", FetchStreamEvent)
        )

        websocket_by_request: dict[str, list[WebSocketEvent]] = defaultdict(list)
        for event in _read_jsonl(folder / "network" / "websocket.jsonl", WebSocketEvent):
            websocket_by_request[event.request_id].append(event)

        return cls(
            http_transactions=transactions,
            server_sent_events=tuple(
                ServerSentEvents(request_id=request_id, events=tuple(events))
                for request_id, events in sse_by_request.items()
            ),
            fetch_stream_events=fetch_events,
            websocket_connections=tuple(
                WebSocketConnection(request_id=request_id, events=tuple(events))
                for request_id, events in websocket_by_request.items()
            ),
        )


ModelT = TypeVar("ModelT", bound=BaseModel)


def _read_jsonl(path: Path, model_type: type[ModelT]) -> list[ModelT]:
    if not path.exists():
        return []
    return [
        model_type.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
