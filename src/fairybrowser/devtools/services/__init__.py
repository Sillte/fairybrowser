import base64
import hashlib
import json
import logging
import re
import shutil
import time
from asyncio.exceptions import CancelledError
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from itertools import count
from pathlib import Path
from threading import Event as ThreadingEvent
from threading import Lock, RLock, Thread, current_thread
from typing import Any, Literal
from urllib.parse import urlparse
from urllib.request import urlopen

import websocket
from playwright._impl._errors import TargetClosedError
from playwright.sync_api import BrowserContext, CDPSession, Frame, Page

from fairybrowser.devtools.event_publisher import EventPublisher
from fairybrowser.devtools.models.fetch_text_stream_event import (
    FetchTextStreamEvent,
)
from fairybrowser.devtools.models.http_transaction import HTTPRequest, HTTPResponse, HTTPTransaction
from fairybrowser.devtools.models.network_log import NetworkLog
from fairybrowser.devtools.models.policy import DevtoolsLogPolicy
from fairybrowser.devtools.models.server_sent_events import ServerSentEvent, ServerSentEvents
from fairybrowser.devtools.models.websockets import WebsocketConnection, WebsocketEvent, WebsocketFrame
from fairybrowser.shared.event import Event

DevtoolsTargetType = Literal["page", "service_worker"]


_FETCH_STREAM_CAPTURE_SCRIPT = r"""
(() => {
  const installedKey = "__fairybrowserFetchStreamHookInstalled";
  if (window[installedKey]) return;
  window[installedKey] = true;

  const originalFetch = window.fetch;
  let nextStreamId = 0;

  window.fetch = async function(input, init) {
    const startedAt = performance.now();
    const response = await originalFetch.call(this, input, init);
    const contentType = response.headers.get("content-type") || "";
    const normalizedType = contentType.toLowerCase();
    const isTextResponse = normalizedType.startsWith("text/") ||
      /json|ndjson|event-stream/.test(normalizedType);

    if (!response.body || !isTextResponse) return response;

    try {
      const clone = response.clone();
      const reader = clone.body.getReader();
      const decoder = new TextDecoder();
      const request = input instanceof Request ? input : null;
      const url = response.url || (request ? request.url : String(input));
      const method = (init && init.method) || (request && request.method) || "GET";
      const streamId = `fetch-${Date.now()}-${++nextStreamId}`;
      const base = {
        stream_id: streamId,
        url,
        method,
        status: response.status,
        content_type: contentType,
      };
      let chunkIndex = 0;

      const emit = async (eventType, text = "", error = null) => {
        try {
          await window.__fairybrowser_capture_fetch_stream({
            ...base,
            event_type: eventType,
            chunk_index: chunkIndex,
            timestamp_ms: performance.timeOrigin + performance.now(),
            elapsed_ms: performance.now() - startedAt,
            text,
            error,
          });
        } catch (_) {}
      };

      void (async () => {
        try {
          while (true) {
            const { value, done } = await reader.read();
            if (done) break;
            const text = decoder.decode(value, { stream: true });
            if (text) {
              await emit("chunk", text);
              chunkIndex += 1;
            }
          }
          const remainder = decoder.decode();
          if (remainder) {
            await emit("chunk", remainder);
            chunkIndex += 1;
          }
          await emit("complete");
        } catch (error) {
          await emit("error", "", String(error));
        }
      })();
    } catch (_) {}

    return response;
  };
})();
"""


def _init_folder(folder: Path):
    if folder.exists():
        shutil.rmtree(folder)
        time.sleep(0.05)
    folder.mkdir(parents=True)


def _error_catcher(function: Callable) -> Callable:
    def _wrapped(*args, **kwargs):
        try:
            function(*args, **kwargs)
        except TargetClosedError as e:
            print("`TargetClosedError`  is invoked @`fairybrowser.devtools.services`", e)
            raise e
        except CancelledError as e:
            print(
                "`asyncio` related... `CancelledError` is invoked @`fairybrowser.devtools.services`",
                e,
            )
            raise e

    return _wrapped


@dataclass
class _RawCommunicationInfo:
    url: str
    method: str
    status: int | None = None
    timing: dict[str, Any] | None = None
    request_headers: dict[str, Any] = field(default_factory=dict)
    response_headers: dict[str, Any] = field(default_factory=dict)
    request_body: bytes | None = None
    response_body: bytes | None = None


def _to_http_transaction(raw: _RawCommunicationInfo) -> HTTPTransaction:
    time_value = 0.0
    if raw.timing:
        for key in ("requestTime", "startTime", "sendStart"):
            if key in raw.timing:
                try:
                    time_value = float(raw.timing[key])
                    break
                except (ValueError, TypeError):
                    pass

    request_body = raw.request_body or b""
    response_body = raw.response_body or b""
    response = None
    if raw.status is not None or raw.response_headers or raw.response_body is not None:
        response = HTTPResponse(status=raw.status, headers=raw.response_headers, body=response_body)
    return HTTPTransaction(
        request=HTTPRequest(
            url=raw.url,
            method=raw.method,
            headers=raw.request_headers,
            body=request_body,
        ),
        response=response,
        time=time_value,
    )


def _dump_request(request_id: str, transactions: list[HTTPTransaction], output_folder: Path):
    sanitized = re.sub(r"[^a-zA-Z0-9_-]", "_", request_id)
    stem = hashlib.sha256(request_id.encode("utf-8")).hexdigest()[:16] if len(sanitized) > 50 else sanitized
    path = output_folder / f"{stem}.json"
    data = [transaction.model_dump(mode="json") for transaction in transactions]
    path.write_text(json.dumps(data, indent=4, ensure_ascii=False))
    logging.info(f"Saved network log to {path}")


def _append_event(
    path: Path,
    event: ServerSentEvent | FetchTextStreamEvent | WebsocketEvent,
):
    with path.open("a", encoding="utf-8") as file:
        file.write(event.model_dump_json() + "\n")


def _safe_request_id_stem(request_id: str) -> str:
    safe_id = re.sub(r"[^a-zA-Z0-9_-]", "_", request_id)[:40] or "request"
    digest = hashlib.sha256(request_id.encode("utf-8")).hexdigest()
    return f"{safe_id}-{digest}"


def _append_id_event(
    folder: Path | None,
    request_id: str,
    event: ServerSentEvent | WebsocketEvent,
):
    if folder is not None:
        _append_event(folder / f"{_safe_request_id_stem(request_id)}.jsonl", event)


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
    def __init__(self, websocket_url: str):
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
                logging.exception("Browser CDP WebSocket receive loop failed")
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
                logging.exception("Browser CDP event handler failed: %s", method)

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

    @staticmethod
    def _invoke_callback(
        callback: Callable[[_CDPCommandResponse], None],
        response: _CDPCommandResponse,
    ) -> None:
        try:
            callback(response)
        except Exception:
            logging.exception("Browser CDP command callback failed")

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
    ):
        self.connection = connection
        self.session_id = session_id
        self.target_id = target_id
        self._on_command_error = on_command_error

    def on(self, event_name: str, handler: Callable[[dict[str, Any]], None]) -> None:
        self.connection.on(event_name, handler, self.session_id)

    def send_no_wait(self, method: str, params: dict[str, Any] | None = None) -> None:
        def log_error(response: _CDPCommandResponse) -> None:
            if response.error is not None:
                logging.warning("CDP command %s failed: %s", method, response.error)
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


class DevtoolsService:
    def __init__(
        self,
        page: Page | Frame,
        output_folder: str | Path | None = None,
        policy: DevtoolsLogPolicy | None = None,
        save_memory: bool = True,
        target_types: Sequence[DevtoolsTargetType] = ("page",),
        browser_cdp_endpoint: str | None = None,
    ):
        if output_folder is None and not save_memory:
            raise ValueError("Provide output_folder or set save_memory=True")
        supported_target_types = {"page", "service_worker"}
        if not target_types or not set(target_types) <= supported_target_types:
            raise ValueError(f"Unsupported DevTools target types: {target_types}")
        if isinstance(page, Frame):
            page = page.page
        self.output_folder = Path(output_folder) if output_folder is not None else None
        if self.output_folder is not None:
            _init_folder(self.output_folder)
        self._page = page
        self.policy = policy if policy is not None else DevtoolsLogPolicy.from_any()
        self._event_publisher = EventPublisher()
        self._network_log = NetworkLog() if save_memory else None
        self._fetch_stream_capture_started = False
        self.target_types = tuple(dict.fromkeys(target_types))
        self.browser_cdp_endpoint = browser_cdp_endpoint
        self._capture_lock = RLock()
        self._cdp_session: CDPSession | None = None
        self._service_worker_cdp: _FlatCDPConnection | None = None
        self._service_worker_sessions: dict[str, _FlatAttachedTargetSession] = {}
        self._service_worker_target_ids: set[str] = set()
        self._service_worker_attach_pending: set[str] = set()

    @property
    def on_http_transaction(self) -> Event[HTTPTransaction]:
        return self._event_publisher.on_http_transaction

    @property
    def on_fetch_stream_event(self) -> Event[FetchTextStreamEvent]:
        return self._event_publisher.on_fetch_stream_event

    @property
    def on_server_sent_event(self) -> Event[ServerSentEvent]:
        return self._event_publisher.on_server_sent_event

    @property
    def on_websocket_event(self) -> Event[WebsocketEvent]:
        return self._event_publisher.on_websocket_event

    @property
    def on_websocket_connection(self) -> Event[WebsocketConnection]:
        return self._event_publisher.on_websocket_connection

    @property
    def page(self) -> Page:
        return self._page

    @property
    def network_log(self) -> NetworkLog | None:
        return self._network_log

    def _serialize(self, handler: Callable[..., Any]) -> Callable[..., Any]:
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            with self._capture_lock:
                return handler(*args, **kwargs)

        return wrapped

    def start(self):
        context = self._to_context(self.page)
        try:
            if "page" in self.target_types:
                client = context.new_cdp_session(self.page)
                self._cdp_session = client
                self._start_network(client)
                if "console" in self.policy.categories:
                    self._start_console(client)
                if "fetch_stream" in self.policy.categories:
                    self._start_fetch_stream_capture()
            service_worker_categories = {"http", "event_source", "websocket", "console"}
            if "service_worker" in self.target_types and service_worker_categories & self.policy.categories:
                if self._cdp_session is None:
                    self._cdp_session = context.new_cdp_session(self.page)
                self._start_service_worker_targets(context)
        except Exception:
            self.terminate()
            raise
        self._event_publisher.start()

    def terminate(self) -> None:
        client = self._cdp_session
        service_worker_client = self._service_worker_cdp
        self._cdp_session = None
        self._service_worker_cdp = None
        try:
            if service_worker_client is not None:
                service_worker_client.close()
        finally:
            try:
                if client is not None:
                    client.detach()
            finally:
                with self._capture_lock:
                    self._service_worker_sessions.clear()
                    self._service_worker_target_ids.clear()
                    self._service_worker_attach_pending.clear()
                self._event_publisher.terminate()

    def _start_service_worker_targets(self, context: BrowserContext) -> None:
        endpoint = self.browser_cdp_endpoint or getattr(context.browser, "_fairybrowser_cdp_endpoint", None)
        if endpoint is None:
            raise ValueError(
                "Service Worker targets require browser_cdp_endpoint unless the Browser came from fairybrowser.runners"
            )

        client = _FlatCDPConnection(_resolve_browser_websocket_url(endpoint))
        self._service_worker_cdp = client
        client.on("Target.attachedToTarget", self._serialize(self._on_target_attached))
        client.on("Target.detachedFromTarget", self._serialize(self._on_target_detached))

        page_client = self._cdp_session
        if page_client is None:
            raise RuntimeError("A Page CDP session is required to discover Service Worker targets")
        page_target_info = page_client.send("Target.getTargetInfo").get("targetInfo", {})
        page_target_id = page_target_info.get("targetId")
        if not page_target_id:
            raise RuntimeError("Could not determine the Page target ID for Service Worker capture")

        try:
            client.send(
                "Target.autoAttachRelated",
                {
                    "targetId": page_target_id,
                    "waitForDebuggerOnStart": True,
                    "filter": [{"type": "service_worker"}],
                },
            )
        except Exception:
            client.on("Target.targetCreated", self._serialize(self._on_target_created))
            client.send("Target.setDiscoverTargets", {"discover": True})
            for target_info in client.send("Target.getTargets").get("targetInfos", []):
                self._attach_service_worker(target_info)

    def _on_target_attached(self, params: dict[str, Any]) -> None:
        target_info = params.get("targetInfo", {})
        target_id = target_info.get("targetId")
        session_id = params.get("sessionId")
        if not target_id or not session_id:
            return
        self._service_worker_attach_pending.discard(target_id)
        if target_info.get("type") != "service_worker":
            self._release_target_session(session_id, target_id, params.get("waitingForDebugger", False))
            return
        self._start_service_worker_session(target_id, session_id, params.get("waitingForDebugger", False))

    def _on_target_created(self, params: dict[str, Any]) -> None:
        self._attach_service_worker(params.get("targetInfo", {}))

    def _on_target_detached(self, params: dict[str, Any]) -> None:
        session = self._service_worker_sessions.pop(params.get("sessionId", ""), None)
        if session is not None:
            session.close()
            self._service_worker_target_ids.discard(session.target_id)
            self._service_worker_attach_pending.discard(session.target_id)

    def _release_target_session(self, session_id: str, target_id: str, resume_first: bool) -> None:
        client = self._service_worker_cdp
        if client is None:
            return

        def detach(_resume_response: _CDPCommandResponse | None = None) -> None:
            def on_detached(response: _CDPCommandResponse) -> None:
                if response.error is not None:
                    logging.warning("Failed to detach target session %s: %s", session_id, response.error)

            try:
                client.send_async("Target.detachFromTarget", {"sessionId": session_id}, on_detached)
            except Exception as error:
                logging.warning("Failed to detach target session %s: %s", session_id, error)

        if not resume_first:
            detach()
            return

        session = _FlatAttachedTargetSession(client, session_id, target_id)
        try:
            session.send_async("Runtime.runIfWaitingForDebugger", {}, detach)
        except Exception as error:
            logging.warning("Failed to resume target session %s before detaching: %s", session_id, error)
            detach()

    def _attach_service_worker(self, target_info: dict[str, Any]) -> None:
        if target_info.get("type") != "service_worker":
            return
        target_id = target_info.get("targetId")
        client = self._service_worker_cdp
        if (
            not target_id
            or client is None
            or target_id in self._service_worker_target_ids
            or target_id in self._service_worker_attach_pending
        ):
            return

        self._service_worker_attach_pending.add(target_id)

        def on_attached(response: _CDPCommandResponse) -> None:
            self._service_worker_attach_pending.discard(target_id)
            if response.error is not None:
                logging.warning("Failed to attach Service Worker target %s: %s", target_id, response.error)
                return
            session_id = (response.result or {}).get("sessionId")
            if session_id and target_id not in self._service_worker_target_ids:
                self._start_service_worker_session(target_id, session_id)

        try:
            client.send_async(
                "Target.attachToTarget",
                {"targetId": target_id, "flatten": True},
                self._serialize(on_attached),
            )
        except Exception:
            self._service_worker_attach_pending.discard(target_id)
            raise

    def _start_service_worker_session(
        self,
        target_id: str,
        session_id: str,
        waiting_for_debugger: bool = False,
    ) -> None:
        client = self._service_worker_cdp
        if client is None:
            return
        if target_id in self._service_worker_target_ids:
            if session_id not in self._service_worker_sessions:
                self._release_target_session(session_id, target_id, waiting_for_debugger)
            return

        self._service_worker_target_ids.add(target_id)
        on_command_error = self._serialize(
            lambda error: self._fail_service_worker_session(target_id, session_id, waiting_for_debugger, error)
        )
        session = _FlatAttachedTargetSession(client, session_id, target_id, on_command_error)
        self._service_worker_sessions[session_id] = session
        try:
            self._start_network(
                session,
                initialize_folders=False,
                request_id_prefix=f"service-worker:{target_id}:",
            )
            if "console" in self.policy.categories:
                self._start_console(session)
        except Exception as error:
            self._fail_service_worker_session(target_id, session_id, waiting_for_debugger, error)
            raise
        if waiting_for_debugger:
            session.send_no_wait("Runtime.runIfWaitingForDebugger")

    def _fail_service_worker_session(
        self,
        target_id: str,
        session_id: str,
        waiting_for_debugger: bool,
        error: Exception,
    ) -> None:
        session = self._service_worker_sessions.pop(session_id, None)
        if session is None:
            return
        self._service_worker_target_ids.discard(target_id)
        self._service_worker_attach_pending.discard(target_id)
        session.close()
        logging.warning("Failed to initialize Service Worker target %s: %s", target_id, error)
        self._release_target_session(session_id, target_id, waiting_for_debugger)

    def _start_fetch_stream_capture(self):
        if self._fetch_stream_capture_started:
            return
        self.page.expose_binding("__fairybrowser_capture_fetch_stream", self._serialize(self._on_fetch_stream_event))
        self.page.add_init_script(script=_FETCH_STREAM_CAPTURE_SCRIPT)
        self.page.evaluate(_FETCH_STREAM_CAPTURE_SCRIPT)
        self._fetch_stream_capture_started = True

    def _on_fetch_stream_event(self, source: dict[str, Any], payload: dict[str, Any]):
        if "fetch_stream" not in self.policy.categories:
            return
        frame = source.get("frame")
        event = FetchTextStreamEvent.model_validate({**payload, "frame_url": getattr(frame, "url", None)})
        if not self.policy.should_save_fetch_stream_event(event):
            return
        self._event_publisher.publish(event)
        if self.network_log is not None:
            self.network_log.add_fetch_stream_event(event)
        if self.output_folder is not None:
            path = self.output_folder / "network" / "fetch_stream.jsonl"
            _append_event(path, event)

    def _send_cdp_command(
        self,
        client: CDPSession | _FlatAttachedTargetSession,
        method: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if isinstance(client, _FlatAttachedTargetSession):
            client.send_no_wait(method, params)
            return {}
        return client.send(method, params)

    # ----------------------
    # Network
    # ----------------------
    def _start_network(
        self,
        client,
        *,
        initialize_folders: bool = True,
        request_id_prefix: str = "",
    ):
        capture_http = "http" in self.policy.categories
        capture_event_source = "event_source" in self.policy.categories
        capture_websocket = "websocket" in self.policy.categories
        network_folder = self.output_folder / "network" if self.output_folder is not None else None
        if network_folder is not None:
            if initialize_folders:
                _init_folder(network_folder)
            else:
                network_folder.mkdir(exist_ok=True)
        if not (capture_http or capture_event_source or capture_websocket):
            return

        redirect_map: dict[str, list[_RawCommunicationInfo]] = {}
        event_stream_folder = network_folder / "event_stream" if capture_event_source and network_folder else None
        websocket_folder = network_folder / "websocket" if capture_websocket and network_folder else None
        if event_stream_folder is not None:
            event_stream_folder.mkdir(exist_ok=True)
        if websocket_folder is not None:
            websocket_folder.mkdir(exist_ok=True)
        request_urls: dict[str, str] = {}
        websocket_urls: dict[str, str] = {}
        server_events: dict[str, list[ServerSentEvent]] = {}
        accepted_server_event_requests: set[str] = set()
        websocket_events: dict[str, list[WebsocketEvent]] = {}
        accepted_websocket_requests: set[str] = set()

        def on_request_will_be_sent(params):
            request_id = f"{request_id_prefix}{params['requestId']}"
            request = params["request"]
            method = request["method"]
            url = request["url"]
            request_urls[request_id] = url
            if not capture_http:
                return
            headers = request.get("headers", {})
            post_data = request.get("postData")
            if isinstance(post_data, str):
                request_body = post_data.encode("utf-8")
            elif post_data is None:
                request_body = None
            else:
                request_body = bytes(post_data)

            if "redirectResponse" in params:
                resp = params["redirectResponse"]
                prev_chain = redirect_map.get(request_id, [])
                prev_chain.append(
                    _RawCommunicationInfo(
                        status=resp["status"],
                        url=resp["url"],
                        method=method,
                        timing=resp.get("timing"),
                        request_headers=headers,
                        response_headers=resp.get("headers"),
                        request_body=request_body,
                        response_body=None,
                    )
                )
                redirect_map[request_id] = prev_chain

            chain = redirect_map.get(request_id, [])
            chain.append(
                _RawCommunicationInfo(
                    url=url,
                    method=method,
                    request_headers=headers,
                    request_body=request_body,
                    response_headers={},
                )
            )
            redirect_map[request_id] = chain

        def on_response_received(params):
            request_id = f"{request_id_prefix}{params['requestId']}"
            response = params["response"]
            chain = redirect_map.get(request_id, [])
            if chain:
                chain[-1].status = response["status"]
                chain[-1].response_headers = response.get("headers")
                chain[-1].timing = response.get("timing")

        def finish_loading(
            request_id: str,
            body_response: dict[str, Any] | None,
            body_error: Exception | None = None,
        ) -> None:
            chain = redirect_map.get(request_id)
            if not chain:
                request_urls.pop(request_id, None)
                return

            if body_error is not None:
                logging.debug("Could not retrieve response body for %s: %s", request_id, body_error)
                chain[-1].response_body = b"<not available>"
            elif body_response is None:
                logging.debug("Network.getResponseBody returned no result for %s", request_id)
                chain[-1].response_body = b"<not available>"
            else:
                body = body_response.get("body", b"")
                if body_response.get("base64Encoded", False):
                    chain[-1].response_body = base64.b64decode(body)
                else:
                    chain[-1].response_body = body.encode("utf-8") if isinstance(body, str) else body

            accepted_transactions = []
            for info in chain:
                transaction = _to_http_transaction(info)
                if self.policy.should_save_transaction(transaction):
                    accepted_transactions.append(transaction)
            for transaction in accepted_transactions:
                self._event_publisher.publish(transaction)
                if self.network_log is not None:
                    self.network_log.add_http_transaction(transaction)
            if accepted_transactions and network_folder is not None:
                _dump_request(request_id, accepted_transactions, network_folder)
            del redirect_map[request_id]
            request_urls.pop(request_id, None)

        def on_loading_finished(params):
            cdp_request_id = params["requestId"]
            request_id = f"{request_id_prefix}{cdp_request_id}"
            if request_id not in redirect_map:
                request_urls.pop(request_id, None)
                return

            if isinstance(client, _FlatAttachedTargetSession):

                def on_body_response(response: _CDPCommandResponse) -> None:
                    finish_loading(request_id, response.result, response.error)

                try:
                    client.send_async(
                        "Network.getResponseBody",
                        {"requestId": cdp_request_id},
                        self._serialize(on_body_response),
                    )
                except Exception as error:
                    finish_loading(request_id, None, error)
                return

            try:
                body_response = client.send("Network.getResponseBody", {"requestId": cdp_request_id})
            except Exception as error:
                finish_loading(request_id, None, error)
            else:
                finish_loading(request_id, body_response)

        def on_loading_failed(params):
            request_id = f"{request_id_prefix}{params['requestId']}"
            request_urls.pop(request_id, None)
            redirect_map.pop(request_id, None)
            server_events.pop(request_id, None)
            accepted_server_event_requests.discard(request_id)

        def on_event_source_message(params):
            request_id = f"{request_id_prefix}{params['requestId']}"
            event = ServerSentEvent(
                request_id=request_id,
                timestamp=params["timestamp"],
                url=request_urls.get(request_id),
                event_name=params.get("eventName", ""),
                event_id=params.get("eventId", ""),
                data=params["data"],
            )
            self._event_publisher.publish(event)
            if request_id in accepted_server_event_requests:
                if self.network_log is not None:
                    self.network_log.add_server_sent_event(event)
                _append_id_event(event_stream_folder, request_id, event)
                return

            events = server_events.setdefault(request_id, [])
            events.append(event)
            grouped_events = ServerSentEvents(request_id=request_id, events=events)
            if self.policy.should_save_server_sent_events(grouped_events):
                for accepted_event in events:
                    if self.network_log is not None:
                        self.network_log.add_server_sent_event(accepted_event)
                    _append_id_event(event_stream_folder, request_id, accepted_event)
                server_events.pop(request_id, None)
                accepted_server_event_requests.add(request_id)

        websocket_event_names = {
            "Network.webSocketCreated": "created",
            "Network.webSocketWillSendHandshakeRequest": "handshake_request",
            "Network.webSocketHandshakeResponseReceived": "handshake_response",
            "Network.webSocketFrameSent": "frame_sent",
            "Network.webSocketFrameReceived": "frame_received",
            "Network.webSocketFrameError": "frame_error",
            "Network.webSocketClosed": "closed",
        }

        def make_websocket_handler(event_type: str):
            def on_websocket_event(params):
                request_id = f"{request_id_prefix}{params['requestId']}"
                url = params.get("url") or websocket_urls.get(request_id)
                if event_type == "created" and url:
                    websocket_urls[request_id] = url

                frame_data = params.get("response")
                has_frame_data = (
                    event_type in {"frame_sent", "frame_received"}
                    and isinstance(frame_data, dict)
                    and {"opcode", "mask", "payloadData"} <= frame_data.keys()
                )
                frame = (
                    WebsocketFrame(
                        opcode=frame_data["opcode"],
                        mask=frame_data["mask"],
                        payload_data=frame_data["payloadData"],
                    )
                    if has_frame_data
                    else None
                )
                event = WebsocketEvent(
                    request_id=request_id,
                    event_type=event_type,
                    timestamp=params.get("timestamp"),
                    url=url,
                    frame=frame,
                    params={
                        key: value
                        for key, value in params.items()
                        if key not in {"requestId", "timestamp", "url"} and not (key == "response" and has_frame_data)
                    },
                )
                self._event_publisher.publish(event)

                if request_id in accepted_websocket_requests:
                    if self.network_log is not None:
                        self.network_log.add_websocket_event(event)
                    _append_id_event(websocket_folder, request_id, event)
                else:
                    events = websocket_events.setdefault(request_id, [])
                    events.append(event)
                    connection = WebsocketConnection(request_id=request_id, events=events)
                    if self.policy.should_save_websocket_connection(connection):
                        for accepted_event in events:
                            if self.network_log is not None:
                                self.network_log.add_websocket_event(accepted_event)
                            _append_id_event(websocket_folder, request_id, accepted_event)
                        websocket_events.pop(request_id, None)
                        accepted_websocket_requests.add(request_id)

                if event_type == "closed":
                    websocket_urls.pop(request_id, None)
                    websocket_events.pop(request_id, None)
                    accepted_websocket_requests.discard(request_id)

            return _error_catcher(self._serialize(on_websocket_event))

        if capture_http or capture_event_source:
            client.on("Network.requestWillBeSent", _error_catcher(self._serialize(on_request_will_be_sent)))
        if capture_http:
            client.on("Network.responseReceived", _error_catcher(self._serialize(on_response_received)))
            client.on("Network.loadingFinished", _error_catcher(self._serialize(on_loading_finished)))
        if capture_http or capture_event_source:
            client.on("Network.loadingFailed", _error_catcher(self._serialize(on_loading_failed)))
        if capture_event_source:
            client.on(
                "Network.eventSourceMessageReceived",
                _error_catcher(self._serialize(on_event_source_message)),
            )
        if capture_websocket:
            for event_name, event_type in websocket_event_names.items():
                client.on(event_name, make_websocket_handler(event_type))
        self._send_cdp_command(client, "Network.enable")

    # ----------------------
    # Console
    # ----------------------
    def _start_console(self, client):
        self._send_cdp_command(client, "Runtime.enable")

        def on_console(params):
            type_ = params.get("type")
            args = params.get("args", [])
            messages = []
            for arg in args:
                val = arg.get("value")
                if val is None:
                    val = arg.get("description", "<complex object>")
                messages.append(str(val))
            print(f"\n💬 Console ({type_}): {' '.join(messages)}")

        client.on("Runtime.consoleAPICalled", self._serialize(on_console))

    # ----------------------
    # Page -> Context
    # ----------------------
    def _to_context(self, page: Page | Frame) -> BrowserContext:
        if isinstance(page, Frame):
            return page.page.context
        elif isinstance(page, Page):
            return page.context
