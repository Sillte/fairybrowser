from dataclasses import dataclass, field
from typing import Any

from fairybrowser.devtools.models.http_transaction import HTTPRequest, HTTPResponse, HTTPTransaction


@dataclass
class RawCommunicationInfo:
    url: str
    method: str
    status: int | None = None
    timing: dict[str, Any] | None = None
    request_headers: dict[str, Any] = field(default_factory=dict)
    response_headers: dict[str, Any] = field(default_factory=dict)
    request_body: bytes | None = None
    response_body: bytes | None = None


def to_http_transaction(raw: RawCommunicationInfo) -> HTTPTransaction:
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
