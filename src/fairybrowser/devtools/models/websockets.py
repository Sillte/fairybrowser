from typing import Sequence

from pydantic import BaseModel, Field, JsonValue


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


class WebSocketConnection(BaseModel, frozen=True):
    request_id: str
    events: Sequence[WebSocketEvent]
