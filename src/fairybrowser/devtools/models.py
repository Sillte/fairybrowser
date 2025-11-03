from pathlib import Path
from typing import Any
from pydantic import BaseModel, JsonValue


class RawCommunicationInfo(BaseModel):
    status: int | None = None
    url: str
    method: str
    timing: dict[str, JsonValue] | None = None
    request_headers: dict[str, JsonValue] | None = None
    response_headers: dict[str, JsonValue] | None = None 
    payload: str | dict[str, JsonValue] | None = None # If possible, payload is a dict.
    body: str | bytes | dict[str, JsonValue] | None = None # If possible, body is a dict.


# [2025/11/02]: Currently, `Console` log not is saved.
class RawConsoleInfoElem(BaseModel):
    value: str | None = None
    description: str = "<complex object>"

class RawConsoleInfo(BaseModel):
    type: str 
    args: list[RawConsoleInfoElem]
