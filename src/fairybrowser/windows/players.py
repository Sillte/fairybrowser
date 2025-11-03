import json
import time
import pyautogui
from pathlib import Path
from fairybrowser.windows.models import (
    MouseEventTypeEnum,
    MouseEvent,
    MouseClickEvent,
    MousePlayEventTypeEnum,
)
from fairybrowser.process_utils import to_foreground
from fairybrowser.windows.editors import to_click_events


class MousePlayer:
    def __init__(self, inputs: str | Path | list):
        self.inputs = inputs
        data = inputs
        if isinstance(data, (str, Path)):
            data = Path(data)
            if not data.exists():
                raise FileNotFoundError(f"No files: {self.inputs}")
            data = json.loads(data.read_text())
            assert isinstance(data, list)
        if isinstance(data, list):
            if isinstance(data[0], dict):
                if data[0]["type"] in {MouseEventTypeEnum.BUTTON}:
                    data = [MouseEvent.model_validate(elem) for elem in data]
                elif data[0]["type"] in {MousePlayEventTypeEnum.CLICK}:
                    data = [MouseClickEvent.model_validate(elem) for elem in data]

            if isinstance(data[0], MouseEvent):
                data = to_click_events(data)

        assert all(isinstance(elem, MouseClickEvent) for elem in data)
        self.events: list[MouseClickEvent] = data

    def start(self, speed: float = 1.0, pid: int | None = None):
        """
        speed: 1.0 は実時間。0.5なら倍速、2.0なら半速。
        pid: if given, the corresponding window becomes the foreground window.
        """

        if not self.events:
            print("⚠️ 再生するイベントがありません。")
            return

        if pid is not None:
            to_foreground(pid)

        print(f"▶️ 1秒後マウス操作を再生します（speed={speed}）")
        time.sleep(1)

        # 時間差を計算
        for i, event in enumerate(self.events):
            if i > 0:
                prev = self.events[i - 1]
                delay = (event.depressed_time - prev.pressed_time) / speed
                if delay > 0:
                    time.sleep(delay)
            self._click(event)

        print("✅ 再生完了！")

    def _click(self, event: MouseClickEvent, duration: float = 0.2):
        pyautogui.moveTo(event.x0, event.y0, duration=duration)
        pyautogui.mouseDown()
        perturbance_time = max(event.duration, 0.05)
        pyautogui.moveTo(
            event.x0 + 1, event.y1 - 1, duration=perturbance_time
        )  # Perturrbance
        pyautogui.moveTo(event.x1, event.y1, duration=0.0001)  # Perturrbance
        pyautogui.mouseUp()


if __name__ == "__main__":
    player = MousePlayer("./mouse_clicks.json")
    player.start(speed=1.0)
