"""Edit the `records` so that it can be  
"""

from fairybrowser.windows.models import MouseEvent, MouseEventTypeEnum , MouseClickEvent


def to_click_events(events: list[MouseEvent]) -> list[MouseClickEvent]:
    mouse_events = sorted(events, key=lambda event: event.time)
    result = []
    pressed_event = None
    depressed_event = None
    for i in range(len(mouse_events)):
        if pressed_event is None:
            if mouse_events[i].pressed:
                pressed_event = mouse_events[i]
                continue
        else:
            if not mouse_events[i].pressed:
                depressed_event = mouse_events[i]
                result.append(MouseClickEvent.from_mouse_button_events(pressed_event, depressed_event))
                pressed_event, depressed_event = None, None
    return result
