from typing import Literal

from pydantic import BaseModel, field_validator

BrowserType = Literal["chrome", "edge"]
SpawnType = Literal["auto", "webdriver", "popen"]


class BrowserInfo(BaseModel, frozen=True):
    name: str = "default_fairy"
    type: BrowserType = "chrome"
    spawn: SpawnType = "auto"

    run_args: str | list[str] | None = None

    @field_validator("type", mode="before")
    @classmethod
    def normalize_legacy_type(cls, value: str) -> str:
        return "chrome" if value == "chromium" else value

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

    @field_validator("type", mode="before")
    @classmethod
    def normalize_legacy_type(cls, value: str) -> str:
        return "chrome" if value == "chromium" else value
