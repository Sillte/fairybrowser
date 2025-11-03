from playwright.sync_api import Page, BrowserContext, Frame
from pathlib import Path
import logging
import hashlib
import json 
import base64
import datetime
import shutil
import time
import re

from fairybrowser.devtools.models import RawCommunicationInfo

def _init_folder(folder: Path):
    if folder.exists():
        shutil.rmtree(folder)
        time.sleep(0.05)
    folder.mkdir(parents=True)

    

def _dump_request(request_id: str, com_infos: list[RawCommunicationInfo], output_folder: Path):
    def _sanitize_or_hash_filename(s: str) -> str:
        sanitized = re.sub(r'[^a-zA-Z0-9_-]', '_', s)
        if len(sanitized) > 50:
            hashed = hashlib.sha256(s.encode()).hexdigest()[:16]
            return hashed
        return sanitized

    stem = _sanitize_or_hash_filename(request_id)
    path = output_folder / f"{stem}.json"


    data = [elem.model_dump() for elem in com_infos]
    path.write_text(json.dumps(data, indent=4, ensure_ascii=False))

    logging.info(f"Saved network log to {path}")


class DevtoolsUser:
    def __init__(self, page: Page | Frame, output_folder: str | Path | None = None):
        if not output_folder:
            timestr = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
            output_folder = Path(f"./debug_{timestr}")
        else:
            output_folder = Path(output_folder)
        _init_folder(output_folder)
        self.output_folder = output_folder
        self.page = page

    def start(self):
        context = self._to_context(self.page)
        client = context.new_cdp_session(self.page)
        self._start_network(client)
        self._start_console(client)

    # ----------------------
    # Network
    # ----------------------
    def _start_network(self, client):
        client.send("Network.enable")
        redirect_map: dict[str, list[RawCommunicationInfo]] = {}
        network_folder = self.output_folder / "network"
        _init_folder(network_folder)

        def on_request_will_be_sent(params):
            request_id = params["requestId"]
            request = params["request"]
            method = request["method"]
            url = request["url"]
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
                prev_chain.append(RawCommunicationInfo(
                    status=resp["status"],
                    url=resp["url"],
                    method=method,
                    timing=resp.get("timing"),
                    request_headers=headers,
                    response_headers=resp.get("headers"),
                    request_body=request_body,
                    response_body=None
                ))
                redirect_map[request_id] = prev_chain

            chain = redirect_map.get(request_id, [])
            chain.append(RawCommunicationInfo(
                url=url,
                method=method,
                request_headers=headers,
                request_body=request_body, 
                response_headers={}, 
            ))
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

                _dump_request(request_id, chain, network_folder)
                del redirect_map[request_id]

        client.on("Network.requestWillBeSent", on_request_will_be_sent)
        client.on("Network.responseReceived", on_response_received)
        client.on("Network.loadingFinished", on_loading_finished)

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
