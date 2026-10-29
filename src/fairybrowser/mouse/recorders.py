import json
import logging
import time
from pathlib import Path
from threading import Event

import pynput

from fairybrowser.mouse.models import MouseEvent, MouseEventTypeEnum


class MouseRecorder:
    def __init__(self, logger: logging.Logger | None = None):
        self.stop_event = Event()
        self.events: list[MouseEvent] = []
        self._logger = logger if logger is not None else logging.getLogger(__name__)

    def start(self, output_path: str | Path | None = None):
        if not output_path:
            output_path = Path("./mouse_clicks.json")
        output_path = Path(output_path)

        # ---- マウスのボタン関連イベント ----
        def _on_click(x, y, button, pressed):
            event = MouseEvent(
                type=MouseEventTypeEnum.BUTTON,
                x=x,
                y=y,
                button=str(button),
                pressed=pressed,
                time=time.time(),
            )
            self.events.append(event)

        # ---- キーボードイベント ----
        def _on_key(key):
            try:
                if key == pynput.keyboard.Key.esc:  # Escキーで停止
                    self._logger.info("ESC detected; mouse recording stopped.")
                    self.stop_event.set()
            except Exception:
                self._logger.exception("Failed to handle keyboard input during mouse recording")

        mouse_listener = pynput.mouse.Listener(on_click=_on_click)
        keyboard_listener = pynput.keyboard.Listener(on_press=_on_key)

        self._logger.info("マウス操作を記録中... ESCキーで停止します")

        mouse_listener.start()
        keyboard_listener.start()

        self.stop_event.wait()

        mouse_listener.stop()
        keyboard_listener.stop()

        output_path.write_text(json.dumps([elem.model_dump() for elem in self.events], indent=4, ensure_ascii=False))
        self._logger.info("マウス操作の記録を保存しました: %s", output_path)


if __name__ == "__main__":
    recorder = MouseRecorder()
    recorder.start()
