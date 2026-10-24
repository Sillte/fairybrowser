import json
from typing import Any

from pydantic import BaseModel, Field, JsonValue, PrivateAttr, field_serializer, field_validator

from fairybrowser.devtools.models.codecs import decode_body_from_json, encode_body_for_json


class HTTPResponse(BaseModel, frozen=True):
    status: int | None = None
    headers: dict[str, JsonValue] = Field(default_factory=dict)
    body: bytes = b""
    _json_cache: JsonValue = PrivateAttr(default=None)
    _json_cached: bool = PrivateAttr(default=False)

    @field_validator("body", mode="before")
    @classmethod
    def _decode_body(cls, value: Any) -> bytes:
        return decode_body_from_json(value) or b""

    @field_serializer("body")
    def _encode_body(self, value: bytes) -> str | dict[str, str] | None:
        return encode_body_for_json(value)

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

    @field_validator("body", mode="before")
    @classmethod
    def _decode_body(cls, value: Any) -> bytes:
        return decode_body_from_json(value) or b""

    @field_serializer("body")
    def _encode_body(self, value: bytes) -> str | dict[str, str] | None:
        return encode_body_for_json(value)

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


class HTTPTransaction(BaseModel, frozen=True):
    request: HTTPRequest
    response: HTTPResponse | None = None
    time: float = 0.0
