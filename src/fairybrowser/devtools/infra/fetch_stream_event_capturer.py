from pathlib import Path
from threading import RLock
from typing import Any

from playwright.sync_api import Page

from fairybrowser.devtools.models.fetch_text_stream_event import (
    FetchTextStreamEvent,
)
from fairybrowser.devtools.models.network_log import NetworkLog
from fairybrowser.devtools.models.policy import (
    DevtoolsLogPolicy,
)

from .event_publisher import EventPublisher


def _append_event(
    path: Path,
    event: FetchTextStreamEvent,
):
    with path.open("a", encoding="utf-8") as file:
        file.write(event.model_dump_json() + "\n")


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


class FetchStreamEventCapturer:
    def __init__(
        self,
        page: Page,
        policy: DevtoolsLogPolicy,
        event_publisher: EventPublisher,
        network_log: NetworkLog | None,
        output_path: Path | None,
    ) -> None:
        self._page = page
        self._policy = policy
        self._network_log = network_log
        self._event_publisher = event_publisher
        self._output_path = output_path
        self._started = False
        self._lock = RLock()

    def start(self) -> None:
        if self._started:
            return
        self._page.expose_binding("__fairybrowser_capture_fetch_stream", self._on_fetch_stream_event)
        self._page.add_init_script(script=_FETCH_STREAM_CAPTURE_SCRIPT)
        self._page.evaluate(_FETCH_STREAM_CAPTURE_SCRIPT)
        self._started = True

    def _on_fetch_stream_event(self, source: dict[str, Any], payload: dict[str, Any]):
        with self._lock:
            if "fetch_stream" not in self._policy.categories:
                return
            frame = source.get("frame")
            event = FetchTextStreamEvent.model_validate({**payload, "frame_url": getattr(frame, "url", None)})
            if not self._policy.should_save_fetch_stream_event(event):
                return
            self._event_publisher.publish(event)
            if self._network_log is not None:
                self._network_log.add_fetch_stream_event(event)
            if self._output_path is not None:
                _append_event(self._output_path, event)
