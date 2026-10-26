import base64
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

from fairybrowser.devtools.infra.cdp.connection import (
    _CDPCommandResponse,
    _FlatAttachedTargetSession,
)
from fairybrowser.devtools.infra.event_publisher import EventPublisher
from fairybrowser.devtools.infra.http_transaction_converter import (
    RawCommunicationInfo,
    to_http_transaction,
)
from fairybrowser.devtools.models.http_transaction import HTTPTransaction
from fairybrowser.devtools.models.network_log import NetworkLog
from fairybrowser.devtools.models.policy import DevtoolsLogPolicy
from fairybrowser.devtools.models.server_sent_events import ServerSentEvent, ServerSentEvents
from fairybrowser.devtools.models.websockets import WebsocketConnection, WebsocketEvent, WebsocketFrame


def _dump_request(
    request_id: str,
    transactions: list[HTTPTransaction],
    output_folder: Path,
    logger: logging.Logger,
) -> None:
    sanitized = re.sub(r"[^a-zA-Z0-9_-]", "_", request_id)
    stem = hashlib.sha256(request_id.encode("utf-8")).hexdigest()[:16] if len(sanitized) > 50 else sanitized
    path = output_folder / f"{stem}.json"
    data = [transaction.model_dump(mode="json") for transaction in transactions]
    path.write_text(json.dumps(data, indent=4, ensure_ascii=False))
    logger.info("Saved network log to %s", path)


def _append_event(path: Path, event: ServerSentEvent | WebsocketEvent) -> None:
    with path.open("a", encoding="utf-8") as file:
        file.write(event.model_dump_json() + "\n")


def _safe_request_id_stem(request_id: str) -> str:
    safe_id = re.sub(r"[^a-zA-Z0-9_-]", "_", request_id)[:40] or "request"
    digest = hashlib.sha256(request_id.encode("utf-8")).hexdigest()
    return f"{safe_id}-{digest}"


def _append_id_event(folder: Path | None, request_id: str, event: ServerSentEvent | WebsocketEvent) -> None:
    if folder is not None:
        _append_event(folder / f"{_safe_request_id_stem(request_id)}.jsonl", event)


def _error_catcher(
    function: Callable[..., Any],
    logger: logging.Logger,
) -> Callable[..., Any]:
    def _wrapped(*args: Any, **kwargs: Any) -> Any:
        try:
            function(*args, **kwargs)
        except TargetClosedError:
            logger.warning("CDP target closed while handling a Network event")
            raise
        except CancelledError:
            logger.info("CDP Network event handling was cancelled")
            raise

    return _wrapped


class NetworkEventCapturer:
    def __init__(
        self,
        policy: DevtoolsLogPolicy,
        event_publisher: EventPublisher,
        network_log: NetworkLog | None,
        output_folder: Path | None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._logger = logger if logger is not None else logging.getLogger(__name__)
        self._policy = policy
        self._event_publisher = event_publisher
        self._network_log = network_log
        self._output_folder = output_folder

    def start(
        self,
        client: Any,
        *,
        serialize: Callable[[Callable[..., Any]], Callable[..., Any]],
        send_command: Callable[[Any, str, dict[str, Any] | None], dict[str, Any]],
        initialize_folders: bool = True,
        request_id_prefix: str = "",
    ) -> None:
        capture_http = "http" in self._policy.categories
        capture_event_source = "event_source" in self._policy.categories
        capture_websocket = "websocket" in self._policy.categories
        network_folder = self._output_folder / "network" if self._output_folder is not None else None
        if network_folder is not None:
            if initialize_folders:
                if network_folder.exists():
                    shutil.rmtree(network_folder)
                    time.sleep(0.05)
                network_folder.mkdir(parents=True)
            else:
                network_folder.mkdir(exist_ok=True)
        if not (capture_http or capture_event_source or capture_websocket):
            return

        redirect_map: dict[str, list[RawCommunicationInfo]] = {}
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

        def on_request_will_be_sent(params: dict[str, Any]) -> None:
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

        def on_response_received(params: dict[str, Any]) -> None:
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
                self._logger.debug("Could not retrieve response body for %s: %s", request_id, body_error)
                chain[-1].response_body = b"<not available>"
            elif body_response is None:
                self._logger.debug("Network.getResponseBody returned no result for %s", request_id)
                chain[-1].response_body = b"<not available>"
            else:
                body = body_response.get("body", b"")
                if body_response.get("base64Encoded", False):
                    chain[-1].response_body = base64.b64decode(body)
                else:
                    chain[-1].response_body = body.encode("utf-8") if isinstance(body, str) else body

            accepted_transactions = []
            for info in chain:
                transaction = to_http_transaction(info)
                if self._policy.should_save_transaction(transaction):
                    accepted_transactions.append(transaction)
            for transaction in accepted_transactions:
                self._event_publisher.publish(transaction)
                if self._network_log is not None:
                    self._network_log.add_http_transaction(transaction)
            if accepted_transactions and network_folder is not None:
                _dump_request(request_id, accepted_transactions, network_folder, self._logger)
            del redirect_map[request_id]
            request_urls.pop(request_id, None)

        def on_loading_finished(params: dict[str, Any]) -> None:
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
                        serialize(on_body_response),
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

        def on_loading_failed(params: dict[str, Any]) -> None:
            request_id = f"{request_id_prefix}{params['requestId']}"
            request_urls.pop(request_id, None)
            redirect_map.pop(request_id, None)
            server_events.pop(request_id, None)
            accepted_server_event_requests.discard(request_id)

        def on_event_source_message(params: dict[str, Any]) -> None:
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
                if self._network_log is not None:
                    self._network_log.add_server_sent_event(event)
                _append_id_event(event_stream_folder, request_id, event)
                return

            events = server_events.setdefault(request_id, [])
            events.append(event)
            grouped_events = ServerSentEvents(request_id=request_id, events=events)
            if self._policy.should_save_server_sent_events(grouped_events):
                for accepted_event in events:
                    if self._network_log is not None:
                        self._network_log.add_server_sent_event(accepted_event)
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

        def make_websocket_handler(event_type: str) -> Callable[[dict[str, Any]], None]:
            def on_websocket_event(params: dict[str, Any]) -> None:
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
                frame = None
                if has_frame_data:
                    assert isinstance(frame_data, dict)
                    frame = WebsocketFrame(
                        opcode=frame_data["opcode"],
                        mask=frame_data["mask"],
                        payload_data=frame_data["payloadData"],
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
                        if key not in {"requestId", "timestamp", "url"}
                        and not (key == "response" and has_frame_data)
                    },
                )
                self._event_publisher.publish(event)

                if request_id in accepted_websocket_requests:
                    if self._network_log is not None:
                        self._network_log.add_websocket_event(event)
                    _append_id_event(websocket_folder, request_id, event)
                else:
                    events = websocket_events.setdefault(request_id, [])
                    events.append(event)
                    connection = WebsocketConnection(request_id=request_id, events=events)
                    if self._policy.should_save_websocket_connection(connection):
                        for accepted_event in events:
                            if self._network_log is not None:
                                self._network_log.add_websocket_event(accepted_event)
                            _append_id_event(websocket_folder, request_id, accepted_event)
                        websocket_events.pop(request_id, None)
                        accepted_websocket_requests.add(request_id)

                if event_type == "closed":
                    websocket_urls.pop(request_id, None)
                    websocket_events.pop(request_id, None)
                    accepted_websocket_requests.discard(request_id)

            return _error_catcher(serialize(on_websocket_event), self._logger)

        if capture_http or capture_event_source:
            client.on(
                "Network.requestWillBeSent",
                _error_catcher(serialize(on_request_will_be_sent), self._logger),
            )
        if capture_http:
            client.on("Network.responseReceived", _error_catcher(serialize(on_response_received), self._logger))
            client.on("Network.loadingFinished", _error_catcher(serialize(on_loading_finished), self._logger))
        if capture_http or capture_event_source:
            client.on("Network.loadingFailed", _error_catcher(serialize(on_loading_failed), self._logger))
        if capture_event_source:
            client.on(
                "Network.eventSourceMessageReceived",
                _error_catcher(serialize(on_event_source_message), self._logger),
            )
        if capture_websocket:
            for event_name, event_type in websocket_event_names.items():
                client.on(event_name, make_websocket_handler(event_type))
        send_command(client, "Network.enable", None)
