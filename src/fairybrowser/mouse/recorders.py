import json
import time
from pathlib import Path
from threading import Event

import pynput

from fairybrowser.mouse.models import MouseEvent, MouseEventTypeEnum


class MouseRecorder:
    def __init__(self):
        self.stop_event = Event()
        self.events: list[MouseEvent] = []

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
                    print("\n🛑 ESC detected — recording stopped.")
                    self.stop_event.set()
            except Exception:
                pass

        mouse_listener = pynput.mouse.Listener(on_click=_on_click)
        keyboard_listener = pynput.keyboard.Listener(on_press=_on_key)

        print("🎬 マウス操作を記録中... ESCキーで停止します")

        mouse_listener.start()
        keyboard_listener.start()

        self.stop_event.wait()

        mouse_listener.stop()
        keyboard_listener.stop()

        output_path.write_text(json.dumps([elem.model_dump() for elem in self.events], indent=4, ensure_ascii=False))
        print(f"💾 記録を保存しました: {output_path}")


if __name__ == "__main__":
    recorder = MouseRecorder()
    recorder.start()
