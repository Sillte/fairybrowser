from typing import Any, Annotated
from pydantic import BaseModel, JsonValue, Field, PrivateAttr
import json
import base64


class RawCommunicationInfo(BaseModel):
    status: int | None = None
    url: str
    method: str
    timing: dict[str, JsonValue] | None = None
    request_headers: Annotated[dict[str, JsonValue], Field(default_factory=dict)]
    response_headers: Annotated[dict[str, JsonValue], Field(default_factory=dict)]
    request_body: bytes | None = None
    response_body: bytes | None = None

    def model_dump(self, **kwargs):
        """bytes を自動で Base64 に変換して出力"""
        d = super().model_dump(**kwargs)
        if self.request_body is not None:
            d['request_body'] = base64.b64encode(self.request_body).decode("ascii")
        if self.response_body is not None:
            d['response_body'] = base64.b64encode(self.response_body).decode("ascii")
        return d

    @classmethod
    def model_validate(cls, data):
        """bytes を Base64 から復元"""
        data = data.copy()
        if 'request_body' in data and data['request_body'] is not None:
            data['request_body'] = base64.b64decode(data['request_body'])
        if 'response_body' in data and data['response_body'] is not None:
            data['response_body'] = base64.b64decode(data['response_body'])
        return super().model_validate(data)


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

        request_bytes = raw.request_body if isinstance(raw.request_body, bytes) else (raw.request_body or b"")
        response_bytes = raw.response_body if isinstance(raw.response_body, bytes) else (raw.response_body or b"")

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
