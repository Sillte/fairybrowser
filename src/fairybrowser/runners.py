from typing import Iterator
import time
from fairybrowser.models import BrowserInfo, BrowserTypeEnum, ExecutionInfo
from fairybrowser.monitors import (
    save_state,
    is_existent,
    load_state,
    get_execution_infos,
    to_browser_info,
    get_pid,
)
from fairybrowser.port_utils import find_available_port
from fairybrowser.utils import get_page
from contextlib import contextmanager
from playwright.sync_api import sync_playwright, Browser
from playwright.sync_api import Playwright, Page

import subprocess
from pathlib import Path


def _run_chromium(info: BrowserInfo) -> ExecutionInfo:
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

    start_port = 13456
    if info.type == BrowserTypeEnum.CHROMIUM:
        path = _get_chromium_path()
        start_port = 13456
    elif info.type == BrowserTypeEnum.EDGE:
        path = _get_edge_path()
        start_port = 18456

    if info.port is None:
        info.port = find_available_port(start=start_port)
    assert info.port is not None

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
        f"--remote-debugging-port={info.port}",
        f"--user-data-dir={user_dir}",
        *default_options,
    ]

    proc = subprocess.Popen([str(path), *options])
    pid = proc.pid
    assert info.port is not None
    execution_info = ExecutionInfo(
        name=info.name, pid=pid, type=info.type, port=info.port
    )
    save_state(execution_info)

    return execution_info


@contextmanager
def sync_browser(info: BrowserInfo | str | None = None) -> Iterator[Browser]:
    """Get `playwright.sync_api.Browser with the context."""

    info = to_browser_info(info)

    if not is_existent(info.name):
        execution_info = _run(info)
    execution_info = load_state(info.name)

    if execution_info.type != info.type:
        raise ValueError("Inconsistency of name and type (e.g. Edge / Chromium).")

    with sync_playwright() as playwright:
        browser = _fetch_browser(playwright, execution_info.port, info.type)
        yield browser


@contextmanager
def sync_page(browser_info: BrowserInfo | str | None = None) -> Iterator[Page]:
    """Acquire the `page`, based on the given information."""
    execs = get_execution_infos()
    if not browser_info:
        execs = [
            elem
            for elem in execs
            if elem.name == browser_info.name and elem.type == browser_info.type
        ]

    if not execs:
        target = _run(browser_info)
    else:
        target = list(execs.values())[0]
    port = target.port
    pid = target.pid
    type = target.type

    with sync_playwright() as playwright:
        browser = _fetch_browser(playwright, port=port, type=type)
        page = get_page(browser, pid)
        if page is not None:
            yield page
        else:
            print("Cannot identify the appropriate `browser`.", flush=True)
            print("Fallback is applied.", flush=True)
            yield browser.new_page()


def _fetch_browser(playwright: Playwright, port: int, type: str) -> Browser:
    assert type in {BrowserTypeEnum.CHROMIUM, BrowserTypeEnum.EDGE}
    address = f"http://localhost:{port}"
    browser = playwright.chromium.connect_over_cdp(address)
    return browser


def _run(info: BrowserInfo | str | None = None) -> ExecutionInfo:
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
