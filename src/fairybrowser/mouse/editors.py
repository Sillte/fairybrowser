"""Edit the `records` so that it can be used for analysis."""

from fairybrowser.mouse.models import MouseClickEvent, MouseEvent


def to_click_events(
    events: list[MouseEvent | MouseClickEvent],
) -> list[MouseClickEvent]:
    def _time_key(event: MouseEvent | MouseClickEvent) -> float:
        if isinstance(event, MouseEvent):
            return event.time
        else:
            return event.pressed_time

    click_events = [elem for elem in events if isinstance(elem, MouseClickEvent)]
    mouse_events = [elem for elem in events if isinstance(elem, MouseEvent)]

    mouse_events = sorted(mouse_events, key=lambda event: _time_key(event))
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
    return sorted([*click_events, *result], key=_time_key)
