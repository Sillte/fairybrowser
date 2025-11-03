from enum import Enum
from typing import Annotated, Self
from pydantic import BaseModel, Field


class MouseEventTypeEnum(str, Enum):
    BUTTON = "button"


# Recorded Event.

class MouseEvent(BaseModel, frozen=True):
    type: MouseEventTypeEnum
    x: float
    y: float
    button: str
    pressed: bool
    time: float

# ---- Modified records. ---


class MousePlayEventTypeEnum(str, Enum):
    CLICK = "click"



class MouseClickEvent(BaseModel, frozen=True):
    type: MousePlayEventTypeEnum = MousePlayEventTypeEnum.CLICK
    x0: Annotated[float, Field(description="X at the pressed point")] 
    y0: Annotated[float, Field(description="Y at the pressed point")]
    x1: Annotated[float, Field(description="X at the depressed point")]
    y1: Annotated[float, Field(description="Y at the depressed point")]
    duration: Annotated[float, Field(description="The time mouse is pressed.")]
    pressed_time: Annotated[float, Field(description="Pressed Time")]
    depressed_time: Annotated[float, Field(description="Depressed Time")]

    @classmethod
    def from_mouse_button_events(cls, pressed_event: MouseEvent, depressed_event: MouseEvent) -> Self:
        return cls(x0=pressed_event.x, y0=pressed_event.y,
                               x1=depressed_event.x, y1=depressed_event.y, 
                               duration=depressed_event.time - pressed_event.time,
                               pressed_time=pressed_event.time, depressed_time=depressed_event.time)
