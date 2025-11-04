from pydantic import BaseModel
from enum import Enum


class BrowserTypeEnum(str, Enum):
    CHROMIUM = "chromium"
    EDGE = "edge"

    def __str__(self) -> str:
        return str(self.value)


class BrowserInfo(BaseModel, frozen=True):
    name: str = "default_fairy"
    type: BrowserTypeEnum = BrowserTypeEnum.CHROMIUM
    run_args: str | list[str] | None = None

    def __hash__(self):
        return hash((self.name, self.type))

    def __eq__(self, other):
        if not isinstance(other, BrowserInfo):
            return NotImplemented
        return (self.name, self.type) == (other.name, other.type)


class ExecutionState(BaseModel, frozen=True):
    name: str
    type: BrowserTypeEnum
    port: int
    pid: int
