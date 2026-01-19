from pydantic import BaseModel
from enum import Enum
from typing import Literal


BrowserType = Literal["chromium", "edge"]
SpawnType = Literal["webdriver", "popen"]


class BrowserInfo(BaseModel, frozen=True):
    name: str = "default_fairy"
    type: BrowserType = "chromium"
    spawn: SpawnType = "webdriver"

    run_args: str | list[str] | None = None

    def __hash__(self):
        return hash((self.name, self.type))

    def __eq__(self, other):
        if not isinstance(other, BrowserInfo):
            return NotImplemented
        return (self.name, self.type) == (other.name, other.type)


class ExecutionState(BaseModel, frozen=True):
    name: str
    type: BrowserType
    port: int
    pid: int
