from typing import Sequence

from pydantic import BaseModel, Field, JsonValue


class WebsocketFrame(BaseModel, frozen=True):
    opcode: int
    mask: bool
    payload_data: str


class WebsocketEvent(BaseModel, frozen=True):
    request_id: str
    event_type: str
    timestamp: float | None = None
    url: str | None = None
    frame: WebsocketFrame | None = None
    params: dict[str, JsonValue] = Field(default_factory=dict)


class WebsocketConnection(BaseModel, frozen=True):
    request_id: str
    events: Sequence[WebsocketEvent]
