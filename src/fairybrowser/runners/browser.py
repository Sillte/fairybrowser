import logging
from collections.abc import Generator
from contextlib import contextmanager

from playwright.sync_api import Browser, Page, Playwright, sync_playwright

from fairybrowser.models import BrowserInfo, BrowserType
from fairybrowser.page_finder import PageFinderProtocol, create_page_finder
from fairybrowser.runners.launcher import (
    find_alternate_execution_state,
    get_execution_state,
    restart_browser,
)


@contextmanager
def sync_browser(
    info: BrowserInfo | str | None = None, *, logger: logging.Logger | None = None
) -> Generator[Browser, None, None]:
    """Get a Playwright Browser connected to the managed browser."""
    _ = logger or logging.getLogger()
    state = get_execution_state(info)
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
    state = get_execution_state(browser_info)
    with sync_playwright() as playwright:
        finder = create_page_finder() if page_finder is None else page_finder
        browser = _try_connect_browser(playwright, state.port, state.type)
        page = _find_live_page(browser, finder, state.pid) if browser is not None else None

        if page is None:
            for alternate_state in find_alternate_execution_state(browser_info, state.pid):
                alternate_browser = _try_connect_browser(playwright, alternate_state.port, alternate_state.type)
                if alternate_browser is None:
                    continue
                alternate_page = _find_live_page(alternate_browser, finder, alternate_state.pid)
                if alternate_page is None:
                    try:
                        alternate_page = _fallback_page(alternate_browser, logger)
                    except Exception:
                        continue
                if alternate_browser.is_connected() and not alternate_page.is_closed():
                    browser, page = alternate_browser, alternate_page
                    break

        if page is None or browser is None or not browser.is_connected():
            logger.warning("No live browser page was found; restarting the browser for its profile.")
            state = restart_browser(browser_info)
            browser = _fetch_browser(playwright, port=state.port, type=state.type)
            page = _fallback_page(browser, logger)
        if page.is_closed():
            raise RuntimeError("The selected page closed while it was being acquired.")
        yield page


def _try_connect_browser(playwright: Playwright, port: int, browser_type: BrowserType) -> Browser | None:
    try:
        browser = _fetch_browser(playwright, port=port, type=browser_type)
        return browser if browser.is_connected() else None
    except Exception:
        return None


def _find_live_page(browser: Browser, finder: PageFinderProtocol, pid: int) -> Page | None:
    try:
        page = finder.get_page(browser, pid)
        return page if browser.is_connected() and page is not None and not page.is_closed() else None
    except Exception:
        return None


def _fallback_page(browser: Browser, logger: logging.Logger) -> Page:
    logger.info("Cannot identify the appropriate `page`, Fallback is applied.")
    contexts = browser.contexts
    for context in contexts:
        if context.pages:
            return context.pages[0]
    if contexts:
        return contexts[0].new_page()
    raise RuntimeError("No context found in the browser, cannot acquire a page.")


def _fetch_browser(playwright: Playwright, port: int, type: BrowserType) -> Browser:
    assert type in {"chrome", "edge"}
    address = f"http://localhost:{port}"
    browser = playwright.chromium.connect_over_cdp(address)
    setattr(browser, "_fairybrowser_cdp_endpoint", address)
    return browser
