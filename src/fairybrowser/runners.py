import subprocess
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

import psutil
from playwright.sync_api import Browser, Page, Playwright, sync_playwright

from fairybrowser.models import BrowserInfo, BrowserType, ExecutionState
from fairybrowser.monitors import (
    get_execution_infos,
    get_pid,
    is_existent,
    load_state,
    save_state,
    to_browser_info,
)
from fairybrowser.port_utils import can_connect_port, find_available_port
from fairybrowser.utils import get_page


def _wait_for_port(port: int, host: str = "127.0.0.1", timeout: float = 10.0):
    start = time.time()
    while time.time() - start < timeout:
        if can_connect_port(port, host):
            return
        else:
            time.sleep(0.1)
    raise TimeoutError(f"Port {port} did not open within {timeout} seconds.")


def _get_browser_pid_by_debug_port(port: int) -> int:
    target_arg = f"--remote-debugging-port={port}"
    candidates: list[int] = []

    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            name = (proc.info["name"] or "").lower()
            if name not in {"chrome.exe", "msedge.exe"}:
                continue

            cmdline = proc.info["cmdline"] or []
            if target_arg not in cmdline:
                continue

            # Chromium の子プロセスを除外する
            if any(arg.startswith("--type=") for arg in cmdline):
                continue

            candidates.append(proc.info["pid"])

        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    if len(candidates) == 1:
        return candidates[0]

    if not candidates:
        raise ValueError(f"No browser process found for {target_arg}.")

    raise ValueError(f"Multiple browser processes found for {target_arg}: {candidates}")


def _run_web_driver(port: int, info: BrowserInfo, options: list[str]) -> ExecutionState:
    options = [*options, f"--remote-debugging-port={port}"]
    from selenium import webdriver

    if info.type == "edge":
        from selenium.webdriver.edge.options import Options

        browser_options = Options()
        browser_options.add_experimental_option("detach", True)
        for option in options:
            browser_options.add_argument(option)
        webdriver.Edge(options=browser_options)
    elif info.type == "chromium":
        from selenium.webdriver.chrome.options import Options

        browser_options = Options()
        browser_options.add_experimental_option("detach", True)
        for option in options:
            browser_options.add_argument(option)
        webdriver.Chrome(options=browser_options)
    else:
        raise ValueError("Invalid Type", info)

    pid = _get_browser_pid_by_debug_port(port)
    execution_info = ExecutionState(name=info.name, pid=pid, type=info.type, port=port)
    return execution_info


def _get_edge_path() -> Path:
    possible_paths = [
        Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"),
        Path("C:/Program Files/Microsoft/Edge/Application/msedge.exe"),
    ]
    for p in possible_paths:
        if p.exists():
            return p
    raise FileNotFoundError("Microsoft Edge executable not found.")


def _get_chromium_path() -> Path:
    with sync_playwright() as p:
        chromium_path = p.chromium.executable_path
    return Path(chromium_path)


def _run_exe(port: int, info: BrowserInfo, options: list[str]) -> ExecutionState:
    if info.type == "edge":
        path = _get_edge_path()
    elif info.type == "chromium":
        path = _get_chromium_path()
    else:
        raise ValueError(f"InvalidInfo, {info=}")

    options = [*options, f"--remote-debugging-port={port}"]

    proc = subprocess.Popen([str(path), *options])
    time.sleep(0.3)  # Chromium群が立ち上がり始める時間

    pid = proc.pid
    execution_info = ExecutionState(name=info.name, pid=pid, type=info.type, port=port)
    return execution_info


def _run_chromium(info: BrowserInfo) -> ExecutionState:
    """Run chrome-based browser."""

    start_port = 13456
    if info.type == "chromium":
        start_port = 13456
    elif info.type == "edge":
        start_port = 18456

    port = find_available_port(start=start_port)
    print("port", port)

    default_options = [
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-infobars",
    ]
    user_dir = Path.home() / f".config/fairybrowser/{info.type}_{info.spawn}/{info.name}"
    options = [
        f"--user-data-dir={user_dir}",
        *default_options,
    ]
    if info.spawn == "webdriver":
        execution_info = _run_web_driver(port, info, options)
    elif info.spawn == "popen":
        execution_info = _run_exe(port, info, options)
    else:
        raise ValueError("Invalid `BrowserInfo.spawn`.")
    save_state(execution_info)
    _wait_for_port(port)
    return execution_info


def _to_apt_execution_state(
    browser_info: BrowserInfo | str | None = None,
) -> ExecutionState:
    if browser_info is not None:
        browser_info = to_browser_info(browser_info)
        if is_existent(browser_info):
            state = load_state(browser_info)
        else:
            state = _run_chromium(browser_info)
    else:
        # If not specified, we would like to acquire the one of active ones.
        execs = get_execution_infos()
        if not execs:
            info = to_browser_info(None)
            state = _run_chromium(info)
        else:
            state = list(execs.values())[0]
    return state


@contextmanager
def sync_browser(info: BrowserInfo | str | None = None) -> Generator[Browser]:
    """Get `playwright.sync_api.Browser with the context."""
    state = _to_apt_execution_state(info)
    with sync_playwright() as playwright:
        browser = _fetch_browser(playwright, state.port, state.type)
        yield browser


@contextmanager
def sync_page(browser_info: BrowserInfo | str | None = None) -> Generator[Page]:
    """Acquire the `page`, based on the given information."""
    state = _to_apt_execution_state(browser_info)
    with sync_playwright() as playwright:
        browser = _fetch_browser(playwright, port=state.port, type=state.type)
        page = get_page(browser, state.pid)
        if page is not None:
            yield page
        else:
            print("Cannot identify the appropriate `page`.", flush=True)
            print("Fallback is applied.", flush=True)
            yield browser.new_page()


def _fetch_browser(playwright: Playwright, port: int, type: BrowserType) -> Browser:
    assert type in {"chromium", "edge"}
    address = f"http://localhost:{port}"
    browser = playwright.chromium.connect_over_cdp(address)
    return browser


if __name__ == "__main__":
    from fairybrowser import BrowserInfo
    from fairybrowser.process_utils import to_foreground
    from fairybrowser.utils import get_page

    info = BrowserInfo(type="edge", spawn="webdriver")
    with sync_page(info) as page:
        pid = get_pid(info)
        assert pid is not None
        print("Return", page.title())
        to_foreground(pid, with_maximize=True)
