from pydantic import BaseModel, JsonValue
from enum import Enum


class BrowserTypeEnum(str, Enum):
    CHROMIUM = "chromium"
    EDGE = "edge"

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




