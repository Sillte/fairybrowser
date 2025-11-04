import time
from typing import Iterator
from fairybrowser.models import BrowserInfo, BrowserTypeEnum, ExecutionState
from fairybrowser.monitors import (
    save_state,
    is_existent,
    load_state,
    get_execution_infos,
    to_browser_info,
    get_pid,
)
from fairybrowser.port_utils import find_available_port, can_connect_port
from fairybrowser.utils import get_page
from contextlib import contextmanager
from playwright.sync_api import sync_playwright, Browser
from playwright.sync_api import Playwright, Page

import subprocess
from pathlib import Path


def _run_chromium(info: BrowserInfo) -> ExecutionState:
    """Run chrome-based browser."""

    def _get_chromium_path() -> Path:
        with sync_playwright() as p:
            chromium_path = p.chromium.executable_path
        return Path(chromium_path)

    def _get_edge_path() -> Path:
        possible_paths = [
            Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"),
            Path("C:/Program Files/Microsoft/Edge/Application/msedge.exe"),
        ]
        for p in possible_paths:
            if p.exists():
                return p
        raise FileNotFoundError("Microsoft Edge executable not found.")

    def _wait_for_port(port: int, host: str = "127.0.0.1", timeout: float = 10.0):
        start = time.time()
        while time.time() - start < timeout:
            if can_connect_port(port, host):
                return
            else:
                time.sleep(0.1)
        raise TimeoutError(f"Port {port} did not open within {timeout} seconds.")

    start_port = 13456
    if info.type == BrowserTypeEnum.CHROMIUM:
        path = _get_chromium_path()
        start_port = 13456
    elif info.type == BrowserTypeEnum.EDGE:
        path = _get_edge_path()
        start_port = 18456

    port = find_available_port(start=start_port)
    print("port", port)

    default_options = [
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-infobars",
    ]
    if info.type == BrowserTypeEnum.CHROMIUM:
        user_dir = Path.home() / f".config/fairybrowser/chromium/{info.name}"
    elif info.type == BrowserTypeEnum.EDGE:
        user_dir = Path.home() / f".config/fairybrowser/edge/{info.name}"
    else:
        raise ValueError("`info.type` is invalid.")

    options = [
        f"--remote-debugging-port={port}",
        f"--user-data-dir={user_dir}",
        *default_options,
    ]

    proc = subprocess.Popen([str(path), *options])
    time.sleep(0.1)  # Chromium群が立ち上がり始める時間
    pid = proc.pid
    execution_info = ExecutionState(name=info.name, pid=pid, type=info.type, port=port)
    save_state(execution_info)
    _wait_for_port(port)

    return execution_info


def _to_apt_execution_state(browser_info: BrowserInfo | str | None = None) -> ExecutionState:
    execs = get_execution_infos()
    if browser_info is not None:
        browser_info = to_browser_info(browser_info)
        if is_existent(browser_info):
            state = load_state(browser_info)
        else:
            state = _run(browser_info)
    else:
        # If not specified, we would like to acquire the one of active ones.
        execs = get_execution_infos()
        if not execs:
            state = _run(info=None)
        else:
            state = list(execs.values())[0]
    return state


@contextmanager
def sync_browser(info: BrowserInfo | str | None = None) -> Iterator[Browser]:
    """Get `playwright.sync_api.Browser with the context."""
    state = _to_apt_execution_state(info)
    with sync_playwright() as playwright:
        browser = _fetch_browser(playwright, state.port, state.type)
        yield browser


@contextmanager
def sync_page(browser_info: BrowserInfo | str | None = None) -> Iterator[Page]:
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


def _fetch_browser(playwright: Playwright, port: int, type: str) -> Browser:
    assert type in {BrowserTypeEnum.CHROMIUM, BrowserTypeEnum.EDGE}
    address = f"http://localhost:{port}"
    browser = playwright.chromium.connect_over_cdp(address)
    return browser


def _run(info: BrowserInfo | str | None = None) -> ExecutionState:
    info = to_browser_info(info)

    if info.type in {BrowserTypeEnum.CHROMIUM, BrowserTypeEnum.EDGE}:
        return _run_chromium(info)
    else:
        msg = f"BrowserType in not apt {info.type}"
        raise ValueError(msg)


if __name__ == "__main__":
    from fairybrowser.utils import get_page
    from fairybrowser.process_utils import to_foreground

    with sync_page() as page:
        pid = get_pid()
        assert pid is not None
        print("Return", page.title())
        to_foreground(pid, with_maximize=True)
