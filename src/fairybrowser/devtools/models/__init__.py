from __future__ import annotations

from typing import Literal

from pydantic import (
    BaseModel,
)


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
