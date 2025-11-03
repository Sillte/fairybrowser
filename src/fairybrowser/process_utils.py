from pydantic import BaseModel
import psutil
import time
import ctypes
import ctypes.wintypes
import win32gui
import win32con
import win32process
import pywintypes

import ctypes
import time



class HwndInfo(BaseModel, frozen=True):
    hwnd: int 
    title: str 
    pid: int 
    thread_id: int 


def get_visible_windows() -> list[HwndInfo]:
    """ Return the hwnd information of visible window. 
    """
    user32 = ctypes.windll.user32
    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)
    infos = list()
    def foreach_window(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            buff = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buff, length + 1)
            pid = ctypes.wintypes.DWORD()
            thread_id = user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if buff.value:
                info = HwndInfo(hwnd=hwnd, title=buff.value, pid=pid.value, thread_id=thread_id)
                infos.append(info)
        return True
    user32.EnumWindows(EnumWindowsProc(foreach_window), 0)
    return infos


def to_foreground(pid: int, with_maximize: bool = False):
    os_infos = get_visible_windows()
    visible_pids = {info.pid for info in os_infos}
    process = psutil.Process()
    descendant_pids = {p.pid for p in process.children(recursive=True)}
    descendant_pids.add(pid)
    target_pids = descendant_pids & visible_pids

    def enum_window_callback(hwnd, _):
        # ウィンドウのプロセスIDを取得
        _, found_pid = win32process.GetWindowThreadProcessId(hwnd)
        if found_pid in target_pids:
            # ウィンドウを最前面に
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)  # 最小化されていたら復帰
            if with_maximize:
                win32gui.ShowWindow(hwnd, win32con.SW_MAXIMIZE)  

            for _ in range(5):
                try:
                    win32gui.SetForegroundWindow(hwnd)
                    print(f"✅ Window {hwnd} brought to foreground")
                    return False  # 見つかったら停止
                except Exception:
                    time.sleep(0.1)
                    continue
            return True

    time.sleep(0.5)
    win32gui.EnumWindows(enum_window_callback, None)




def to_foreground(pid: int, with_maximize: bool = True):
    user32 = ctypes.windll.user32

    EnumWindows = user32.EnumWindows
    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)
    SetForegroundWindow = user32.SetForegroundWindow
    ShowWindow = user32.ShowWindow
    IsWindowVisible = user32.IsWindowVisible
    WS_OVERLAPPEDWINDOW = 0x00CF0000
    GWL_STYLE = -16
    SW_MAXIMIZE = 3
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
    if with_maximize:
        ShowWindow(hwnd, SW_MAXIMIZE)
    SetForegroundWindow(hwnd)

        



if __name__ == "__main__":
    pass

