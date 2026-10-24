from queue import Queue
from threading import RLock, Thread, current_thread
from typing import Literal, assert_never

from fairybrowser.devtools.models import FetchStreamEvent
from fairybrowser.devtools.models.http_transaction import HTTPTransaction
from fairybrowser.devtools.models.server_sent_events import ServerSentEvent
from fairybrowser.devtools.models.websockets import WebSocketConnection, WebSocketEvent
from fairybrowser.shared.event import Event, EventEmitter

type BrowserEvent = HTTPTransaction | FetchStreamEvent | ServerSentEvent | WebSocketEvent | WebSocketConnection
type Status = Literal["created", "running", "terminated"]


class EventPublisher:
    def __init__(self) -> None:
        self._queue = Queue[BrowserEvent | None]()
        self._http_transaction_emitter = EventEmitter[HTTPTransaction]()
        self._fetch_stream_event_emitter = EventEmitter[FetchStreamEvent]()
        self._server_sent_event_emitter = EventEmitter[ServerSentEvent]()
        self._websocket_event_emitter = EventEmitter[WebSocketEvent]()
        self._websocket_connection_emitter = EventEmitter[WebSocketConnection]()
        self._status: Status = "created"
        self._thread = Thread(target=self._loop, daemon=True)
        self._lock = RLock()

    @property
    def on_http_transaction(self) -> Event[HTTPTransaction]:
        with self._lock:
            if self._status != "created":
                raise ValueError("Subscription is possible only before `start`.")
        return self._http_transaction_emitter.event

    @property
    def on_fetch_stream_event(self) -> Event[FetchStreamEvent]:
        with self._lock:
            if self._status != "created":
                raise ValueError("Subscription is possible only before `start`.")
        return self._fetch_stream_event_emitter.event

    @property
    def on_server_sent_event(self) -> Event[ServerSentEvent]:
        with self._lock:
            if self._status != "created":
                raise ValueError("Subscription is possible only before `start`.")
        return self._server_sent_event_emitter.event

    @property
    def on_websocket_event(self) -> Event[WebSocketEvent]:
        with self._lock:
            if self._status != "created":
                raise ValueError("Subscription is possible only before `start`.")
        return self._websocket_event_emitter.event

    @property
    def on_websocket_connection(self) -> Event[WebSocketConnection]:
        with self._lock:
            if self._status != "created":
                raise ValueError("Subscription is possible only before `start`.")
        return self._websocket_connection_emitter.event

    def start(self) -> None:
        with self._lock:
            if self._status != "created":
                raise RuntimeError(f"`self._status` must be `created`, but `{self._status=}`")
            self._status = "running"
        self._thread.start()

    def terminate(self) -> None:
        with self._lock:
            if self._status == "terminated":
                return
            self._status = "terminated"
            self._queue.put(None)
        if self._thread.is_alive() and current_thread() is not self._thread:
            self._thread.join()

    def publish(self, browser_event: BrowserEvent) -> None:
        self._queue.put(browser_event)

    def _loop(self) -> None:
        while True:
            browser_event = self._queue.get()
            if browser_event is None:
                return
            match browser_event:
                case HTTPTransaction():
                    self._http_transaction_emitter.fire(browser_event)
                case FetchStreamEvent():
                    self._fetch_stream_event_emitter.fire(browser_event)
                case ServerSentEvent():
                    self._server_sent_event_emitter.fire(browser_event)
                case WebSocketEvent():
                    self._websocket_event_emitter.fire(browser_event)
                case WebSocketConnection():
                    self._websocket_connection_emitter.fire(browser_event)
                case _:
                    assert_never(browser_event)
