import base64
import hashlib
import json
import logging
import re
import shutil
import time
from asyncio.exceptions import CancelledError
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from playwright._impl._errors import TargetClosedError
from playwright.sync_api import BrowserContext, Frame, Page

from fairybrowser.devtools.event_publisher import EventPublisher
from fairybrowser.devtools.models import (
    FetchStreamEvent,
)
from fairybrowser.devtools.models.http_transaction import HTTPRequest, HTTPResponse, HTTPTransaction
from fairybrowser.devtools.models.network_log import NetworkLog
from fairybrowser.devtools.models.policy import DevtoolsLogPolicy
from fairybrowser.devtools.models.server_sent_events import ServerSentEvent, ServerSentEvents
from fairybrowser.devtools.models.websockets import WebSocketConnection, WebSocketEvent, WebSocketFrame

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

      const emit = async (eventType, data = "", error = null) => {
        try {
          await window.__fairybrowser_capture_fetch_stream({
            ...base,
            event_type: eventType,
            chunk_index: chunkIndex,
            timestamp_ms: performance.timeOrigin + performance.now(),
            elapsed_ms: performance.now() - startedAt,
            data,
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
            print("`TargetClosedError`  is invoked @`fairybrowser.devtools.collectors`", e)
            raise e
        except CancelledError as e:
            print(
                "`asyncio` related... `CancelledError` is invoked @`fairybrowser.devtools.collectors`",
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
    event: ServerSentEvent | FetchStreamEvent | WebSocketEvent,
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
    event: ServerSentEvent | WebSocketEvent,
):
    if folder is not None:
        _append_event(folder / f"{_safe_request_id_stem(request_id)}.jsonl", event)


class DevtoolsUser:
    def __init__(
        self,
        page: Page | Frame,
        output_folder: str | Path | None = None,
        policy: DevtoolsLogPolicy | None = None,
        save_memory: bool = False,
    ):
        if output_folder is None and not save_memory:
            raise ValueError("Provide output_folder or set save_memory=True")
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

    @property
    def event_publisher(self) -> EventPublisher:
        return self._event_publisher

    @property
    def page(self) -> Page:
        return self._page

    @property
    def network_log(self) -> NetworkLog | None:
        return self._network_log

    def start(self):
        context = self._to_context(self.page)
        client = context.new_cdp_session(self.page)
        self._start_network(client)
        if "console" in self.policy.categories:
            self._start_console(client)
        if "fetch_stream" in self.policy.categories:
            self._start_fetch_stream_capture()
        self._event_publisher.start()

    def terminate(self) -> None:
        self._event_publisher.terminate()

    def _start_fetch_stream_capture(self):
        if self._fetch_stream_capture_started:
            return
        self.page.expose_binding("__fairybrowser_capture_fetch_stream", self._on_fetch_stream_event)
        self.page.add_init_script(script=_FETCH_STREAM_CAPTURE_SCRIPT)
        self.page.evaluate(_FETCH_STREAM_CAPTURE_SCRIPT)
        self._fetch_stream_capture_started = True

    def _on_fetch_stream_event(self, source: dict[str, Any], payload: dict[str, Any]):
        if "fetch_stream" not in self.policy.categories:
            return
        frame = source.get("frame")
        event = FetchStreamEvent.model_validate({**payload, "frame_url": getattr(frame, "url", None)})
        self._event_publisher.publish(event)
        if self.network_log is not None:
            self.network_log.add_fetch_stream_event(event)
        if self.output_folder is not None:
            path = self.output_folder / "network" / "fetch_stream.jsonl"
            _append_event(path, event)

    # ----------------------
    # Network
    # ----------------------
    def _start_network(self, client):
        capture_http = "http" in self.policy.categories
        capture_event_source = "event_source" in self.policy.categories
        capture_websocket = "websocket" in self.policy.categories
        network_folder = self.output_folder / "network" if self.output_folder is not None else None
        if network_folder is not None:
            _init_folder(network_folder)
        if not (capture_http or capture_event_source or capture_websocket):
            return

        redirect_map: dict[str, list[_RawCommunicationInfo]] = {}
        event_stream_folder = network_folder / "event_stream" if capture_event_source and network_folder else None
        websocket_folder = network_folder / "websocket" if capture_websocket and network_folder else None
        if event_stream_folder is not None:
            event_stream_folder.mkdir()
        if websocket_folder is not None:
            websocket_folder.mkdir()
        request_urls: dict[str, str] = {}
        websocket_urls: dict[str, str] = {}
        server_events: dict[str, list[ServerSentEvent]] = {}
        accepted_server_event_requests: set[str] = set()
        websocket_events: dict[str, list[WebSocketEvent]] = {}
        accepted_websocket_requests: set[str] = set()

        def on_request_will_be_sent(params):
            request_id = params["requestId"]
            request = params["request"]
            method = request["method"]
            url = request["url"]
            request_urls[request_id] = url
            if not capture_http:
                return
            headers = request.get("headers", {})
            post_data = request.get("postData")
            if isinstance(post_data, str):
                request_body = post_data.encode("utf-8")  # str -> bytes
            elif post_data is None:
                request_body = None
            else:
                request_body = bytes(post_data)  # 万が一 bytes ならそのまま

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
            request_id = params["requestId"]
            response = params["response"]
            chain = redirect_map.get(request_id, [])
            if chain:
                chain[-1].status = response["status"]
                chain[-1].response_headers = response.get("headers")
                chain[-1].timing = response.get("timing")

        def on_loading_finished(params):
            request_id = params["requestId"]
            chain = redirect_map.get(request_id, [])
            if chain:
                try:
                    body_resp = client.send("Network.getResponseBody", {"requestId": request_id})
                    body = body_resp.get("body", b"")
                    if body_resp.get("base64Encoded", False):
                        chain[-1].response_body = base64.b64decode(body)
                    else:
                        # plain textの場合も bytes に統一
                        chain[-1].response_body = body.encode("utf-8") if isinstance(body, str) else body
                except Exception:
                    chain[-1].response_body = b"<not available>"

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

        def on_loading_failed(params):
            request_id = params["requestId"]
            request_urls.pop(request_id, None)
            redirect_map.pop(request_id, None)
            server_events.pop(request_id, None)
            accepted_server_event_requests.discard(request_id)

        def on_event_source_message(params):
            request_id = params["requestId"]
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
                request_id = params["requestId"]
                url = params.get("url") or websocket_urls.get(request_id)
                if event_type == "created" and url:
                    websocket_urls[request_id] = url

                frame_data = params.get("response")
                frame = (
                    WebSocketFrame(
                        opcode=frame_data["opcode"],
                        mask=frame_data["mask"],
                        payload_data=frame_data["payloadData"],
                    )
                    if frame_data is not None
                    else None
                )
                event = WebSocketEvent(
                    request_id=request_id,
                    event_type=event_type,
                    timestamp=params.get("timestamp"),
                    url=url,
                    frame=frame,
                    params={
                        key: value
                        for key, value in params.items()
                        if key not in {"requestId", "timestamp", "url", "response"}
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
                    connection = WebSocketConnection(request_id=request_id, events=events)
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

            return _error_catcher(on_websocket_event)

        if capture_http or capture_event_source:
            client.on("Network.requestWillBeSent", _error_catcher(on_request_will_be_sent))
        if capture_http:
            client.on("Network.responseReceived", _error_catcher(on_response_received))
            client.on("Network.loadingFinished", _error_catcher(on_loading_finished))
        if capture_http or capture_event_source:
            client.on("Network.loadingFailed", _error_catcher(on_loading_failed))
        if capture_event_source:
            client.on(
                "Network.eventSourceMessageReceived",
                _error_catcher(on_event_source_message),
            )
        if capture_websocket:
            for event_name, event_type in websocket_event_names.items():
                client.on(event_name, make_websocket_handler(event_type))
        client.send("Network.enable")

    # ----------------------
    # Console
    # ----------------------
    def _start_console(self, client):
        client.send("Runtime.enable")

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

        client.on("Runtime.consoleAPICalled", on_console)

    # ----------------------
    # Page -> Context
    # ----------------------
    def _to_context(self, page: Page | Frame) -> BrowserContext:
        if isinstance(page, Frame):
            return page.page.context
        elif isinstance(page, Page):
            return page.context
