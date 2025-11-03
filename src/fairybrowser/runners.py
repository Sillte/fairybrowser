from typing import Iterator
from fairybrowser.models import BrowserInfo, BrowserTypeEnum, ExecutionInfo
from fairybrowser.monitors import save_state, is_existent, load_state, get_execution_infos, to_browser_info, get_pid
from fairybrowser.port_utils import find_available_port
from fairybrowser.utils import get_page
from contextlib import contextmanager
from playwright.sync_api import sync_playwright, Browser
from playwright.sync_api import Playwright, Page

import subprocess
from pathlib import Path

def _run_chromium(info:BrowserInfo) -> ExecutionInfo:
    def _get_chromium_path() -> Path:
        with sync_playwright() as p:
            chromium_path = p.chromium.executable_path
        return Path(chromium_path)
    path = _get_chromium_path()
    if info.port is None:
        info.port = find_available_port(start=13456)
    assert info.port is not None

    default_options =  ["--no-first-run",
                        "--no-default-browser-check"
                        "--disable-infobars"]
    options = [
        f"--remote-debugging-port={info.port}",
        f"--user-data-dir=./tmp/{info.name}",
        *default_options, 
    ]

    proc = subprocess.Popen([str(path), *options])
    pid = proc.pid
    assert info.port is not None
    execution_info = ExecutionInfo(name=info.name, pid=pid, type=info.type, port=info.port)
    save_state(execution_info)
    import time 
    time.sleep(1)
    return execution_info



@contextmanager
def sync_browser(info: BrowserInfo | str | None = None) -> Iterator[Browser]:
    """Get `playwright.sync_api.Browser with the context."""

    info = to_browser_info(info)

    if not is_existent(info.name):
        execution_info = _run(info)
    execution_info = load_state(info.name)

    with sync_playwright() as playwright:
        browser = _fetch_browser(playwright, execution_info.port, info.type)
        yield browser

@contextmanager
def sync_page(browser_info: BrowserInfo | str | None=None) -> Iterator[Page]:
    """Acquire the `page`, based on the given information.
    """
    execs = get_execution_infos()
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
    assert type == BrowserTypeEnum.CHROMIUM
    address = f"http://localhost:{port}"
    browser = playwright.chromium.connect_over_cdp(address)
    return browser
    
def _run(info: BrowserInfo | str | None = None) -> ExecutionInfo: 
    info = to_browser_info(info)

    if info.type ==  BrowserTypeEnum.CHROMIUM:
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

