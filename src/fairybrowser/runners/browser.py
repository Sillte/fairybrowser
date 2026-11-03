import logging
from collections.abc import Generator
from contextlib import contextmanager

from playwright.sync_api import Browser, Page, Playwright, sync_playwright

from fairybrowser.models import BrowserInfo, BrowserType
from fairybrowser.page_finder import PageFinderProtocol, create_page_finder
from fairybrowser.runners.launcher import get_execution_state, restart_browser


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
        browser = _fetch_browser(playwright, port=state.port, type=state.type)
        finder = create_page_finder() if page_finder is None else page_finder
        for attempt in range(2):
            if not browser.is_connected():
                if attempt == 1:
                    raise RuntimeError("Browser disconnected while acquiring a page.")
                logger.warning("Browser disconnected while acquiring a page; reconnecting to CDP.")
                browser = _fetch_browser(playwright, port=state.port, type=state.type)
                continue

            try:
                page = finder.get_page(browser, state.pid)
                if page is not None and page.is_closed():
                    logger.info("Page finder returned a closed page; using a fallback page.")
                    page = None
                if page is None:
                    logger.warning("No live page was found; restarting the browser for its profile.")
                    state = restart_browser(browser_info)
                    browser = _fetch_browser(playwright, port=state.port, type=state.type)
                    page = _fallback_page(browser, logger)
                if page.is_closed():
                    raise RuntimeError("The selected page closed while it was being acquired.")
            except Exception:
                if attempt == 0 and not browser.is_connected():
                    logger.warning("Browser disconnected while acquiring a page; reconnecting to CDP.")
                    browser = _fetch_browser(playwright, port=state.port, type=state.type)
                    continue
                raise

            if not browser.is_connected():
                if attempt == 0:
                    logger.warning("Browser disconnected while acquiring a page; reconnecting to CDP.")
                    browser = _fetch_browser(playwright, port=state.port, type=state.type)
                    continue
                raise RuntimeError("Browser disconnected while acquiring a page.")
            yield page
            return


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
    assert type in {"chromium", "edge"}
    address = f"http://localhost:{port}"
    browser = playwright.chromium.connect_over_cdp(address)
    setattr(browser, "_fairybrowser_cdp_endpoint", address)
    return browser
