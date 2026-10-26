import logging
import shutil
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from threading import RLock
from typing import Any, Literal

from playwright.sync_api import BrowserContext, CDPSession, Frame, Page

from fairybrowser.devtools.infra.cdp.connection import (
    _CDPCommandResponse,
    _FlatAttachedTargetSession,
    _FlatCDPConnection,
    _resolve_browser_websocket_url,
)
from fairybrowser.devtools.infra.cdp.network_event_capturer import NetworkEventCapturer
from fairybrowser.devtools.infra.event_publisher import EventPublisher
from fairybrowser.devtools.infra.fetch_stream_event_capturer import FetchStreamEventCapturer
from fairybrowser.devtools.models.fetch_text_stream_event import (
    FetchTextStreamEvent,
)
from fairybrowser.devtools.models.http_transaction import HTTPTransaction
from fairybrowser.devtools.models.network_log import NetworkLog
from fairybrowser.devtools.models.policy import DevtoolsLogPolicy
from fairybrowser.devtools.models.server_sent_events import ServerSentEvent
from fairybrowser.devtools.models.websockets import WebsocketConnection, WebsocketEvent
from fairybrowser.shared.event import Event

DevtoolsTargetType = Literal["page", "service_worker"]


def _init_folder(folder: Path):
    if folder.exists():
        shutil.rmtree(folder)
        time.sleep(0.05)
    folder.mkdir(parents=True)


class DevtoolsService:
    def __init__(
        self,
        page: Page | Frame,
        output_folder: str | Path | None = None,
        policy: DevtoolsLogPolicy | None = None,
        save_memory: bool = True,
        target_types: Sequence[DevtoolsTargetType] = ("page",),
        browser_cdp_endpoint: str | None = None,
        logger: logging.Logger | None = None,
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
        self._logger = logger if logger is not None else logging.getLogger(__name__)
        self.policy = policy if policy is not None else DevtoolsLogPolicy.from_any()
        self._event_publisher = EventPublisher()
        self._network_log = NetworkLog() if save_memory else None
        self._network_event_capturer = NetworkEventCapturer(
            self.policy,
            self._event_publisher,
            self._network_log,
            self.output_folder,
            self._logger,
        )
        fetch_stream_path = (
            self.output_folder / "network" / "fetch_stream.jsonl" if self.output_folder is not None else None
        )
        self._fetch_stream_capturer = FetchStreamEventCapturer(
            page,
            self.policy,
            self._event_publisher,
            self._network_log,
            fetch_stream_path,
        )
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

        client = _FlatCDPConnection(_resolve_browser_websocket_url(endpoint), self._logger)
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
                    self._logger.warning("Failed to detach target session %s: %s", session_id, response.error)

            try:
                client.send_async("Target.detachFromTarget", {"sessionId": session_id}, on_detached)
            except Exception as error:
                self._logger.warning("Failed to detach target session %s: %s", session_id, error)

        if not resume_first:
            detach()
            return

        session = _FlatAttachedTargetSession(client, session_id, target_id, logger=self._logger)
        try:
            session.send_async("Runtime.runIfWaitingForDebugger", {}, detach)
        except Exception as error:
            self._logger.warning("Failed to resume target session %s before detaching: %s", session_id, error)
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
                self._logger.warning("Failed to attach Service Worker target %s: %s", target_id, response.error)
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
        session = _FlatAttachedTargetSession(client, session_id, target_id, on_command_error, self._logger)
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
        self._logger.warning("Failed to initialize Service Worker target %s: %s", target_id, error)
        self._release_target_session(session_id, target_id, waiting_for_debugger)

    def _start_fetch_stream_capture(self):
        self._fetch_stream_capturer.start()

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
    ) -> None:
        self._network_event_capturer.start(
            client,
            serialize=self._serialize,
            send_command=self._send_cdp_command,
            initialize_folders=initialize_folders,
            request_id_prefix=request_id_prefix,
        )

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
