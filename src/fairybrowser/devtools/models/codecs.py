import base64
from typing import Any


def _utf8_decode_or_none(data: bytes) -> str | None:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def encode_body_for_json(body: bytes | None) -> str | dict[str, str] | None:
    if body is None:
        return None
    if text := _utf8_decode_or_none(body):
        return text
    return {
        "type": "bytes",
        "data": base64.b64encode(body).decode("ascii"),
    }


def decode_body_from_json(value: Any) -> bytes | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value.encode("utf-8")
    if isinstance(value, dict) and value.get("type") == "bytes" and "data" in value:
        return base64.b64decode(value["data"])
    raise ValueError(f"Invalid body format: {value!r}")
