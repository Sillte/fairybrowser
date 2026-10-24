import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from fairybrowser.devtools.models.fetch_text_stream_event import FetchTextStreamEvent
from fairybrowser.devtools.models.http_transaction import HTTPTransaction
from fairybrowser.devtools.models.server_sent_events import ServerSentEvent, ServerSentEvents
from fairybrowser.devtools.models.websockets import WebsocketConnection, WebsocketEvent


class NetworkLogSnapshot(BaseModel, frozen=True):
    http_transactions: tuple[HTTPTransaction, ...] = ()
    server_sent_events: tuple[ServerSentEvents, ...] = ()
    fetch_stream_events: tuple[FetchTextStreamEvent, ...] = ()
    websocket_connections: tuple[WebsocketConnection, ...] = ()


@dataclass
class NetworkLog:
    http_transactions: list[HTTPTransaction] = field(default_factory=list)
    fetch_stream_events: list[FetchTextStreamEvent] = field(default_factory=list)
    _server_sent_events: dict[str, list[ServerSentEvent]] = field(default_factory=dict, repr=False)
    _websocket_events: dict[str, list[WebsocketEvent]] = field(default_factory=dict, repr=False)

    @property
    def server_sent_events(self) -> tuple[ServerSentEvents, ...]:
        return tuple(
            ServerSentEvents(request_id=request_id, events=tuple(events))
            for request_id, events in self._server_sent_events.items()
        )

    @property
    def websocket_connections(self) -> tuple[WebsocketConnection, ...]:
        return tuple(
            WebsocketConnection(request_id=request_id, events=tuple(events))
            for request_id, events in self._websocket_events.items()
        )

    def add_http_transaction(self, transaction: HTTPTransaction) -> None:
        self.http_transactions.append(transaction)

    def add_server_sent_event(self, event: ServerSentEvent) -> None:
        self._server_sent_events.setdefault(event.request_id, []).append(event)

    def add_fetch_stream_event(self, event: FetchTextStreamEvent) -> None:
        self.fetch_stream_events.append(event)

    def add_websocket_event(self, event: WebsocketEvent) -> None:
        self._websocket_events.setdefault(event.request_id, []).append(event)

    def get_http_transactions(self, method: str | None = None, path: str | None = None) -> list[HTTPTransaction]:
        transactions = self.http_transactions
        if method:
            transactions = [transaction for transaction in transactions if method.lower() in transaction.request.method.lower()]
        if path:
            transactions = [transaction for transaction in transactions if path.lower() in transaction.request.url.lower()]
        return transactions

    def snapshot(self) -> NetworkLogSnapshot:
        return NetworkLogSnapshot(
            http_transactions=tuple(self.http_transactions),
            server_sent_events=self.server_sent_events,
            fetch_stream_events=tuple(self.fetch_stream_events),
            websocket_connections=self.websocket_connections,
        )

    @classmethod
    def load(cls, log_folder: str | Path) -> "NetworkLog":
        folder = Path(log_folder)
        if not folder.is_dir():
            raise FileNotFoundError(f"Network log folder does not exist: {folder}")

        network_log = cls()
        for path in sorted((*folder.glob("*.json"), *folder.glob("network/*.json"))):
            data = json.loads(path.read_text(encoding="utf-8"))
            entries = data if isinstance(data, list) else [data]
            for entry in entries:
                network_log.add_http_transaction(HTTPTransaction.model_validate(entry))

        network_folder = folder / "network"
        for event in _read_grouped_jsonl(network_folder / "event_stream", ServerSentEvent):
            network_log.add_server_sent_event(event)
        for event in _read_jsonl(network_folder / "fetch_stream.jsonl", FetchTextStreamEvent):
            network_log.add_fetch_stream_event(event)
        for event in _read_grouped_jsonl(network_folder / "websocket", WebsocketEvent):
            network_log.add_websocket_event(event)
        return network_log


ModelT = TypeVar("ModelT", bound=BaseModel)


def _read_jsonl(path: Path, model_type: type[ModelT]) -> list[ModelT]:
    if not path.exists():
        return []
    return [
        model_type.model_validate_json(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def _read_grouped_jsonl(folder: Path, model_type: type[ModelT]) -> list[ModelT]:
    return [event for path in sorted(folder.glob("*.jsonl")) for event in _read_jsonl(path, model_type)]
