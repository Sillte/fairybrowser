import base64
import json
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    Field,
    JsonValue,
    PrivateAttr,
    field_serializer,
    field_validator,
)


def _utf8_decode_or_none(data: bytes) -> str | None:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _encode_body_for_json(body: bytes | None) -> str | dict[str, str] | None:
    if body is None:
        return None
    if text := _utf8_decode_or_none(body):
        return text
    return {
        "type": "bytes",
        "data": base64.b64encode(body).decode("ascii"),
    }


def _decode_body_from_json(value: Any) -> bytes | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value.encode("utf-8")
    if isinstance(value, dict) and value.get("type") == "bytes" and "data" in value:
        return base64.b64decode(value["data"])
    raise ValueError(f"Invalid body format: {value!r}")


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


class EventStreamMessage(BaseModel, frozen=True):
    request_id: str
    timestamp: float
    url: str | None = None
    event_name: str = ""
    event_id: str = ""
    data: str


class FetchStreamEvent(BaseModel, frozen=True):
    stream_id: str
    event_type: Literal["chunk", "complete", "error"]
    url: str
    method: str
    status: int
    frame_url: str | None = None
    content_type: str | None = None
    chunk_index: int
    timestamp_ms: float
    elapsed_ms: float
    data: str = ""
    error: str | None = None


class WebSocketFrame(BaseModel, frozen=True):
    opcode: int
    mask: bool
    payload_data: str


class WebSocketEvent(BaseModel, frozen=True):
    request_id: str
    event_type: str
    timestamp: float | None = None
    url: str | None = None
    frame: WebSocketFrame | None = None
    params: dict[str, JsonValue] = Field(default_factory=dict)


class SimpleRequest(BaseModel, frozen=True):
    """Simple HTTP Request.
    bytesベースで保存しつつ、text/jsonへの変換をプロパティで提供。
    """

    status: int | None = None
    url: str
    method: str
    time: float  # 相対秒
    request_headers: Annotated[dict[str, JsonValue], Field(default_factory=dict)]
    response_headers: Annotated[dict[str, JsonValue], Field(default_factory=dict)]
    request_body: bytes
    response_body: bytes

    # 内部キャッシュ用
    _request_json: dict | str | None = PrivateAttr(default=None)
    _response_json: dict | str | None = PrivateAttr(default=None)

    # --- request関連 ---
    @property
    def request_bytes(self) -> bytes:
        return self.request_body

    @property
    def request_text(self) -> str:
        return self.request_body.decode("utf-8", errors="replace")

    @property
    def request_json(self) -> dict | str:
        if self._request_json is not None:
            return self._request_json
        try:
            self._request_json = json.loads(self.request_text)
        except (ValueError, UnicodeDecodeError):
            self._request_json = self.request_text
        return self._request_json

    # 別名 alias
    payload = property(lambda self: self.request_json)

    # --- response関連 ---
    @property
    def response_bytes(self) -> bytes:
        return self.response_body

    @property
    def response_text(self) -> str:
        return self.response_body.decode("utf-8", errors="replace")

    @property
    def response_json(self) -> dict | str:
        if self._response_json is not None:
            return self._response_json
        try:
            self._response_json = json.loads(self.response_text)
        except (ValueError, UnicodeDecodeError):
            self._response_json = self.response_text
        return self._response_json

    # 別名 alias
    response_data = property(lambda self: self.response_json)

    # --- Raw → SimpleRequest 変換 ---
    @classmethod
    def from_raw(cls, raw: "RawCommunicationInfo") -> "SimpleRequest":
        """RawCommunicationInfo → SimpleRequest に変換"""
        # --- 相対時間（秒）を取得 ---
        time_value: float = 0.0
        if raw.timing:
            for key in ("requestTime", "startTime", "sendStart"):
                if key in raw.timing:
                    try:
                        time_value = float(raw.timing[key])
                        break
                    except (ValueError, TypeError):
                        pass

        request_bytes = (
            raw.request_body
            if isinstance(raw.request_body, bytes)
            else (raw.request_body or b"")
        )
        response_bytes = (
            raw.response_body
            if isinstance(raw.response_body, bytes)
            else (raw.response_body or b"")
        )

        return cls(
            status=raw.status,
            url=raw.url,
            method=raw.method,
            time=time_value,
            request_headers=raw.request_headers or {},
            response_headers=raw.response_headers or {},
            request_body=request_bytes,
            response_body=response_bytes,
        )
