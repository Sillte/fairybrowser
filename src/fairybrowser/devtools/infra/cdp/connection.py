import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from itertools import count
from threading import Event as ThreadingEvent
from threading import Lock, RLock, Thread, current_thread
from typing import Any
from urllib.parse import urlparse
from urllib.request import urlopen

import websocket


@dataclass(frozen=True)
class _CDPCommandResponse:
    result: dict[str, Any] | None = None
    error: Exception | None = None


class _CDPCommandError(RuntimeError):
    def __init__(self, method: str, error: dict[str, Any]):
        self.method = method
        self.code = error.get("code")
        self.data = error.get("data")
        super().__init__(error.get("message", "CDP command failed"))


def _resolve_browser_websocket_url(endpoint: str) -> str:
    parsed = urlparse(endpoint)
    if parsed.scheme in {"ws", "wss"}:
        return endpoint
    if parsed.scheme not in {"http", "https"}:
        raise ValueError(f"Unsupported browser CDP endpoint: {endpoint}")

    version_url = (
        endpoint if parsed.path.rstrip("/").endswith("/json/version") else endpoint.rstrip("/") + "/json/version"
    )
    with urlopen(version_url, timeout=5) as response:
        websocket_url = json.load(response).get("webSocketDebuggerUrl")
    if not websocket_url:
        raise RuntimeError(f"Browser did not provide a CDP WebSocket URL at {version_url}")
    return websocket_url


class _FlatCDPConnection:
    def __init__(self, websocket_url: str, logger: logging.Logger | None = None):
        self._logger = logger if logger is not None else logging.getLogger(__name__)
        self._websocket = websocket.create_connection(websocket_url, timeout=10, suppress_origin=True)
        self._websocket.settimeout(None)
        self._lock = RLock()
        self._send_lock = Lock()
        self._next_command_id = count(1)
        self._handlers: dict[tuple[str | None, str], list[Callable[[dict[str, Any]], None]]] = {}
        self._sync_pending: dict[int, tuple[ThreadingEvent, dict[str, Any]]] = {}
        self._async_pending: dict[
            int,
            tuple[str | None, str, Callable[[_CDPCommandResponse], None]],
        ] = {}
        self._closed = False
        self._receiver = Thread(target=self._receive_loop, daemon=True)
        self._receiver.start()

    def on(
        self,
        event_name: str,
        handler: Callable[[dict[str, Any]], None],
        session_id: str | None = None,
    ) -> None:
        with self._lock:
            self._handlers.setdefault((session_id, event_name), []).append(handler)

    def send(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        session_id: str | None = None,
        timeout: float = 10,
    ) -> dict[str, Any]:
        command_id = next(self._next_command_id)
        completed = ThreadingEvent()
        pending = {"result": None, "error": None}
        with self._lock:
            self._ensure_open()
            self._sync_pending[command_id] = (completed, pending)
        try:
            self._send_message(command_id, method, params, session_id)
        except Exception:
            with self._lock:
                self._sync_pending.pop(command_id, None)
            raise
        if not completed.wait(timeout):
            with self._lock:
                self._sync_pending.pop(command_id, None)
            raise TimeoutError(f"Timed out waiting for CDP command: {method}")
        if pending["error"] is not None:
            raise RuntimeError(f"CDP command failed: {method}: {pending['error']}")
        result = pending["result"] or {}
        return result

    def send_async(
        self,
        method: str,
        params: dict[str, Any] | None,
        callback: Callable[[_CDPCommandResponse], None],
        session_id: str | None = None,
    ) -> None:
        command_id = next(self._next_command_id)
        with self._lock:
            self._ensure_open()
            self._async_pending[command_id] = (session_id, method, callback)
        try:
            self._send_message(command_id, method, params, session_id)
        except Exception:
            with self._lock:
                self._async_pending.pop(command_id, None)
            raise

    def cancel_session(self, session_id: str) -> None:
        with self._lock:
            pending = [
                self._async_pending.pop(command_id)[2]
                for command_id, (pending_session_id, _, _) in tuple(self._async_pending.items())
                if pending_session_id == session_id
            ]
        response = _CDPCommandResponse(error=ConnectionError(f"CDP target session detached: {session_id}"))
        for callback in pending:
            self._invoke_callback(callback, response)

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("Browser CDP connection is closed")

    def _send_message(
        self,
        command_id: int,
        method: str,
        params: dict[str, Any] | None,
        session_id: str | None,
    ) -> None:
        message: dict[str, Any] = {"id": command_id, "method": method, "params": params or {}}
        if session_id is not None:
            message["sessionId"] = session_id
        with self._send_lock:
            self._websocket.send(json.dumps(message))

    def _receive_loop(self) -> None:
        connection_error: Exception = ConnectionError("Browser CDP connection closed")
        try:
            while True:
                raw_message = self._websocket.recv()
                if not raw_message:
                    break
                self._dispatch(json.loads(raw_message))
        except Exception as error:
            connection_error = ConnectionError(f"Browser CDP WebSocket receive failed: {error}")
            if not self._closed:
                self._logger.exception("Browser CDP WebSocket receive loop failed")
        finally:
            with self._lock:
                self._closed = True
            self._fail_pending(connection_error)

    def _dispatch(self, message: dict[str, Any]) -> None:
        if "id" in message:
            command_id = message["id"]
            with self._lock:
                sync_pending = self._sync_pending.pop(command_id, None)
                async_pending = self._async_pending.pop(command_id, None)
            if sync_pending is not None:
                completed, pending = sync_pending
                pending["result"] = message.get("result")
                pending["error"] = message.get("error")
                completed.set()
            elif async_pending is not None:
                _, method, callback = async_pending
                if "error" in message:
                    response = _CDPCommandResponse(error=_CDPCommandError(method, message["error"]))
                else:
                    response = _CDPCommandResponse(result=message.get("result"))
                self._invoke_callback(callback, response)
            return

        method = message.get("method")
        if method is None:
            return
        session_id = message.get("sessionId")
        with self._lock:
            handlers = tuple(self._handlers.get((session_id, method), ()))
        for handler in handlers:
            try:
                handler(message.get("params", {}))
            except Exception:
                self._logger.exception("Browser CDP event handler failed: %s", method)

    def _fail_pending(self, error: Exception) -> None:
        with self._lock:
            sync_pending, self._sync_pending = self._sync_pending, {}
            async_pending, self._async_pending = self._async_pending, {}
        for completed, pending in sync_pending.values():
            pending["error"] = {"message": str(error)}
            completed.set()
        response = _CDPCommandResponse(error=error)
        for _, _, callback in async_pending.values():
            self._invoke_callback(callback, response)

    def _invoke_callback(
        self,
        callback: Callable[[_CDPCommandResponse], None],
        response: _CDPCommandResponse,
    ) -> None:
        try:
            callback(response)
        except Exception:
            self._logger.exception("Browser CDP command callback failed")

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        try:
            self._websocket.close()
        finally:
            if self._receiver.is_alive() and current_thread() is not self._receiver:
                self._receiver.join(timeout=2)
            self._fail_pending(ConnectionError("Browser CDP connection closed"))


class _FlatAttachedTargetSession:
    def __init__(
        self,
        connection: _FlatCDPConnection,
        session_id: str,
        target_id: str,
        on_command_error: Callable[[Exception], None] | None = None,
        logger: logging.Logger | None = None,
    ):
        self.connection = connection
        self.session_id = session_id
        self.target_id = target_id
        self._on_command_error = on_command_error
        self._logger = logger if logger is not None else connection._logger

    def on(self, event_name: str, handler: Callable[[dict[str, Any]], None]) -> None:
        self.connection.on(event_name, handler, self.session_id)

    def send_no_wait(self, method: str, params: dict[str, Any] | None = None) -> None:
        def log_error(response: _CDPCommandResponse) -> None:
            if response.error is not None:
                self._logger.warning("CDP command %s failed: %s", method, response.error)
                if self._on_command_error is not None:
                    self._on_command_error(response.error)

        self.connection.send_async(method, params, log_error, self.session_id)

    def send_async(
        self,
        method: str,
        params: dict[str, Any],
        callback: Callable[[_CDPCommandResponse], None],
    ) -> None:
        self.connection.send_async(method, params, callback, self.session_id)

    def close(self) -> None:
        self.connection.cancel_session(self.session_id)
