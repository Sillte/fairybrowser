from typing import Literal

from pydantic import BaseModel, Field


class FetchTextStreamEvent(BaseModel, frozen=True):
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
    text: str = Field(default="")
    error: str | None = None
