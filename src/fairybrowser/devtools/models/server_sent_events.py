from typing import Sequence

from pydantic import BaseModel


class ServerSentEvent(BaseModel, frozen=True):
    request_id: str
    timestamp: float
    url: str | None = None
    event_name: str = ""
    event_id: str = ""
    data: str


class ServerSentEvents(BaseModel, frozen=True):
    """Container for Server-Sent Events from the same EventSource request."""

    request_id: str
    events: Sequence[ServerSentEvent]
