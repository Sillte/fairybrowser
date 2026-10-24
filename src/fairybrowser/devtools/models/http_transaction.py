import json
from typing import Any

from pydantic import BaseModel, Field, JsonValue, PrivateAttr, field_serializer, field_validator

from fairybrowser.devtools.models.codecs import _decode_body_from_json, _encode_body_for_json


class HTTPResponse(BaseModel, frozen=True):
    status: int | None = None
    headers: dict[str, JsonValue] = Field(default_factory=dict)
    body: bytes = b""
    _json_cache: JsonValue = PrivateAttr(default=None)
    _json_cached: bool = PrivateAttr(default=False)

    @property
    def body_text(self) -> str:
        return self.body.decode("utf-8", errors="replace")

    @property
    def body_json(self) -> JsonValue:
        if self._json_cached:
            return self._json_cache
        try:
            self._json_cache = json.loads(self.body_text)
        except ValueError:
            self._json_cache = self.body_text
        self._json_cached = True
        return self._json_cache


class HTTPRequest(BaseModel, frozen=True):
    url: str
    method: str
    headers: dict[str, JsonValue] = Field(default_factory=dict)
    body: bytes = b""
    _json_cache: JsonValue = PrivateAttr(default=None)
    _json_cached: bool = PrivateAttr(default=False)

    @property
    def body_text(self) -> str:
        return self.body.decode("utf-8", errors="replace")

    @property
    def body_json(self) -> JsonValue:
        if self._json_cached:
            return self._json_cache
        try:
            self._json_cache = json.loads(self.body_text)
        except ValueError:
            self._json_cache = self.body_text
        self._json_cached = True
        return self._json_cache

    @property
    def payload(self) -> JsonValue:
        return self.body_json


class RawCommunicationInfo(BaseModel):
    status: int | None = None
    url: str
    method: str
    timing: dict[str, JsonValue] | None = None
    request_headers: dict[str, JsonValue] = Field(default_factory=dict)
    response_headers: dict[str, JsonValue] = Field(default_factory=dict)
    request_body: bytes | None = None
    response_body: bytes | None = None

    @field_validator("request_body", "response_body", mode="before")
    @classmethod
    def _decode_body(cls, v: Any):
        return _decode_body_from_json(v)

    @field_serializer("request_body", "response_body")
    def _encode_body(self, v: Any, _):
        return _encode_body_for_json(v)


class HTTPTransaction(BaseModel, frozen=True):
    request: HTTPRequest
    response: HTTPResponse | None = None
    time: float = 0.0

    @classmethod
    def from_raw(cls, raw: "RawCommunicationInfo") -> "HTTPTransaction":
        time_value: float = 0.0
        if raw.timing:
            for key in ("requestTime", "startTime", "sendStart"):
                if key in raw.timing:
                    try:
                        time_value = float(raw.timing[key])  # type: ignore
                        break
                    except (ValueError, TypeError):
                        pass

        request_bytes = raw.request_body if isinstance(raw.request_body, bytes) else (raw.request_body or b"")
        response_bytes = raw.response_body if isinstance(raw.response_body, bytes) else (raw.response_body or b"")
        response = None
        if raw.status is not None or raw.response_headers or raw.response_body is not None:
            response = HTTPResponse(
                status=raw.status,
                headers=raw.response_headers or {},
                body=response_bytes,
            )
        return cls(
            request=HTTPRequest(
                url=raw.url,
                method=raw.method,
                headers=raw.request_headers or {},
                body=request_bytes,
            ),
            response=response,
            time=time_value,
        )
