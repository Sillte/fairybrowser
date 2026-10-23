import base64
import datetime
import hashlib
import json
import logging
import re
import shutil
import time
from asyncio.exceptions import CancelledError
from collections.abc import Callable
from pathlib import Path
from typing import Any

from playwright._impl._errors import TargetClosedError
from playwright.sync_api import BrowserContext, Frame, Page

from fairybrowser.devtools.models import (
    EventStreamMessage,
    FetchStreamEvent,
    RawCommunicationInfo,
    WebSocketEvent,
    WebSocketFrame,
)

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
            print(
                "`TargetClosedError`  is invoked @`fairybrowser.devtools.collectors`", e
            )
            raise e
        except CancelledError as e:
            print(
                "`asyncio` related... `CancelledError` is invoked @`fairybrowser.devtools.collectors`",
                e,
            )
            raise e

    return _wrapped


def _dump_request(
    request_id: str, com_infos: list[RawCommunicationInfo], output_folder: Path
):
    def _sanitize_or_hash_filename(s: str) -> str:
        sanitized = re.sub(r"[^a-zA-Z0-9_-]", "_", s)
        if len(sanitized) > 50:
            hashed = hashlib.sha256(s.encode()).hexdigest()[:16]
            return hashed
        return sanitized

    stem = _sanitize_or_hash_filename(request_id)
    path = output_folder / f"{stem}.json"

    data = [elem.model_dump() for elem in com_infos]
    path.write_text(json.dumps(data, indent=4, ensure_ascii=False))

    logging.info(f"Saved network log to {path}")


def _append_event(
    path: Path,
    event: EventStreamMessage | FetchStreamEvent | WebSocketEvent,
):
    with path.open("a", encoding="utf-8") as file:
        file.write(event.model_dump_json() + "\n")


class DevtoolsUser:
    def __init__(self, page: Page | Frame, output_folder: str | Path | None = None):
        if isinstance(page, Frame):
            page = page.page
        if not output_folder:
            timestr = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
            output_folder = Path(f"./debug_{timestr}")
        else:
            output_folder = Path(output_folder)
        _init_folder(output_folder)
        self.output_folder = output_folder
        self.page = page
        self._fetch_stream_capture_started = False

    def start(self):
        context = self._to_context(self.page)
        client = context.new_cdp_session(self.page)
        self._start_network(client)
        self._start_console(client)
        self._start_fetch_stream_capture()

    def _start_fetch_stream_capture(self):
        if self._fetch_stream_capture_started:
            return
        self.page.expose_binding(
            "__fairybrowser_capture_fetch_stream", self._on_fetch_stream_event
        )
        self.page.add_init_script(script=_FETCH_STREAM_CAPTURE_SCRIPT)
        self.page.evaluate(_FETCH_STREAM_CAPTURE_SCRIPT)
        self._fetch_stream_capture_started = True

    def _on_fetch_stream_event(self, source: dict[str, Any], payload: dict[str, Any]):
        frame = source.get("frame")
        event = FetchStreamEvent.model_validate(
            {**payload, "frame_url": getattr(frame, "url", None)}
        )
        path = self.output_folder / "network" / "fetch_stream.jsonl"
        _append_event(path, event)

    # ----------------------
    # Network
    # ----------------------
    def _start_network(self, client):
        redirect_map: dict[str, list[RawCommunicationInfo]] = {}
        network_folder = self.output_folder / "network"
        _init_folder(network_folder)
        event_stream_path = network_folder / "event_stream.jsonl"
        websocket_path = network_folder / "websocket.jsonl"
        request_urls: dict[str, str] = {}
        websocket_urls: dict[str, str] = {}

        def on_request_will_be_sent(params):
            request_id = params["requestId"]
            request = params["request"]
            method = request["method"]
            url = request["url"]
            request_urls[request_id] = url
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
                    RawCommunicationInfo(
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
                RawCommunicationInfo(
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
                    body_resp = client.send(
                        "Network.getResponseBody", {"requestId": request_id}
                    )
                    body = body_resp.get("body", b"")
                    if body_resp.get("base64Encoded", False):
                        chain[-1].response_body = base64.b64decode(body)
                    else:
                        # plain textの場合も bytes に統一
                        chain[-1].response_body = (
                            body.encode("utf-8") if isinstance(body, str) else body
                        )
                except Exception:
                    chain[-1].response_body = b"<not available>"

                _dump_request(request_id, chain, network_folder)
                del redirect_map[request_id]
            request_urls.pop(request_id, None)

        def on_event_source_message(params):
            request_id = params["requestId"]
            event = EventStreamMessage(
                request_id=request_id,
                timestamp=params["timestamp"],
                url=request_urls.get(request_id),
                event_name=params.get("eventName", ""),
                event_id=params.get("eventId", ""),
                data=params["data"],
            )
            _append_event(event_stream_path, event)

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
                _append_event(websocket_path, event)

                if event_type == "closed":
                    websocket_urls.pop(request_id, None)

            return _error_catcher(on_websocket_event)

        client.on("Network.requestWillBeSent", _error_catcher(on_request_will_be_sent))
        client.on("Network.responseReceived", _error_catcher(on_response_received))
        client.on("Network.loadingFinished", _error_catcher(on_loading_finished))
        client.on(
            "Network.eventSourceMessageReceived",
            _error_catcher(on_event_source_message),
        )
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
