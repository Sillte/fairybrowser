from pydantic import BaseModel
from enum import Enum


class BrowserTypeEnum(str, Enum):
    CHROMIUM = "chromium"
    EDGE = "edge"

    def __str__(self) -> str:
        return str(self.value)


class BrowserInfo(BaseModel):
    name: str = "default_fairy"
    type: str = BrowserTypeEnum.CHROMIUM
    port: int | None = None
    run_args: str | list[str] | None = None


class ExecutionInfo(BaseModel, frozen=True):
    name: str
    type: str
    port: int
    pid: int
