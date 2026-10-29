import logging
from collections.abc import Generator
from contextlib import contextmanager

from playwright.sync_api import Browser, Page, Playwright, sync_playwright

from fairybrowser.models import BrowserInfo, BrowserType, ExecutionState
from fairybrowser.monitors import (
    get_execution_infos,
    is_existent,
    load_state,
    to_browser_info,
)
from fairybrowser.page_finder import PageFinderProtocol, create_page_finder
from fairybrowser.runners.launcher import _run_chromium


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
        execs = get_execution_infos()
        if not execs:
            state = _run_chromium(to_browser_info(None))
        else:
            state = list(execs.values())[0]
    return state


@contextmanager
def sync_browser(
    info: BrowserInfo | str | None = None, *, logger: logging.Logger | None = None
) -> Generator[Browser, None, None]:
    """Get a Playwright Browser connected to the managed browser."""
    _ = logger or logging.getLogger()
    state = _to_apt_execution_state(info)
    with sync_playwright() as playwright:
        browser = _fetch_browser(playwright, state.port, state.type)
        yield browser


@contextmanager
def sync_page(
    browser_info: BrowserInfo | str | None = None,
    *,
    page_finder: PageFinderProtocol | None = None,
    logger: logging.Logger | None = None,
) -> Generator[Page, None, None]:
    """Acquire a page from the managed browser."""
    logger = logger or logging.getLogger()
    state = _to_apt_execution_state(browser_info)
    with sync_playwright() as playwright:
        browser = _fetch_browser(playwright, port=state.port, type=state.type)
        finder = create_page_finder() if page_finder is None else page_finder
        page = finder.get_page(browser, state.pid)
        if page is not None:
            yield page
        else:
            logger.info("Cannot identify the appropriate `page`, Fallback is applied.")
            yield browser.new_page()


def _fetch_browser(playwright: Playwright, port: int, type: BrowserType) -> Browser:
    assert type in {"chromium", "edge"}
    address = f"http://localhost:{port}"
    browser = playwright.chromium.connect_over_cdp(address)
    setattr(browser, "_fairybrowser_cdp_endpoint", address)
    return browser
