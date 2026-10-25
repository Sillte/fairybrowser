import ctypes
import ctypes.wintypes
import time

import psutil
from pydantic import BaseModel


class HwndInfo(BaseModel, frozen=True):
    hwnd: int
    title: str
    pid: int
    thread_id: int


def get_visible_windows() -> list[HwndInfo]:
    """Return the hwnd information of visible windows."""
    user32 = ctypes.windll.user32
    enum_windows_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)
    infos = []

    def foreach_window(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, length + 1)
            pid = ctypes.wintypes.DWORD()
            thread_id = user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if buffer.value:
                infos.append(HwndInfo(hwnd=hwnd, title=buffer.value, pid=pid.value, thread_id=thread_id))
        return True

    user32.EnumWindows(enum_windows_proc(foreach_window), 0)
    return infos


def to_foreground(pid: int, with_maximize: bool = True):
    import win32con
    import win32gui  # type: ignore
    import win32process  # type: ignore

    user32 = ctypes.windll.user32

    EnumWindows = user32.EnumWindows
    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)
    ShowWindow = user32.ShowWindow
    IsWindowVisible = user32.IsWindowVisible
    WS_OVERLAPPEDWINDOW = 0x00CF0000
    GWL_STYLE = -16
    SW_RESTORE = win32con.SW_RESTORE
    SW_MAXIMIZE = win32con.SW_MAXIMIZE

    def _find_hwnd_by_pid(pid, timeout=1):
        hwnd_found = None
        os_infos = get_visible_windows()
        visible_pids = {info.pid for info in os_infos}
        process = psutil.Process()
        descendant_pids = {p.pid for p in process.children(recursive=True)}
        descendant_pids.add(pid)
        target_pids = descendant_pids & visible_pids

        def get_window_title(hwnd):
            length = win32gui.GetWindowTextLength(hwnd)
            return win32gui.GetWindowText(hwnd) if length > 0 else ""

        def callback(hwnd, lParam):
            nonlocal hwnd_found
            if not IsWindowVisible(hwnd):
                return True

            _, wnd_pid = win32process.GetWindowThreadProcessId(hwnd)
            if wnd_pid not in target_pids:
                return True
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_STYLE)
            title = get_window_title(hwnd)
            if style & WS_OVERLAPPEDWINDOW and title:
                hwnd_found = hwnd
                return False  # stop enumeration
            return True

        proc = EnumWindowsProc(callback)
        end = time.time() + timeout
        while time.time() < end and hwnd_found is None:
            EnumWindows(proc, 0)
            if hwnd_found is None:
                time.sleep(0.1)
        return hwnd_found

    hwnd = _find_hwnd_by_pid(pid)
    if hwnd is None:
        return

    ShowWindow(hwnd, SW_RESTORE)
    if with_maximize:
        ShowWindow(hwnd, SW_MAXIMIZE)

    for _ in range(5):
        try:
            win32gui.SetForegroundWindow(hwnd)
            return
        except Exception:
            time.sleep(0.1)


if __name__ == "__main__":
    pass
