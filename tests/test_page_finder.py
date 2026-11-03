import logging
from contextlib import nullcontext
from types import SimpleNamespace
from typing import cast

import pytest
from playwright.sync_api import Browser, Page

from fairybrowser.page_finder import windows
from fairybrowser.page_finder.linux import LinuxPageFinder
from fairybrowser.page_finder.windows.process_utils import HwndInfo
from fairybrowser.runners import browser as browser_runner
from fairybrowser.runners import launcher


def test_windows_page_finder_selects_page_matching_visible_browser_window():
    selected_page = SimpleNamespace(url="https://example.com", title=lambda: "Example")
    context = SimpleNamespace(
        pages=[selected_page],
        new_cdp_session=lambda _page: SimpleNamespace(send=lambda _command: {"bounds": {"windowState": "maximized"}}),
    )
    browser = SimpleNamespace(contexts=[context])

    assert (
        windows._find_page_for_windows(
            cast(Browser, browser),
            [HwndInfo(hwnd=1, title="Example - Browser", pid=42, thread_id=1)],
            {42},
        )
        is selected_page
    )


def test_linux_page_finder_returns_the_first_page_across_contexts():
    first_page = object()
    browser = SimpleNamespace(
        contexts=[
            SimpleNamespace(pages=[first_page, object()]),
            SimpleNamespace(pages=[object()]),
        ]
    )

    assert LinuxPageFinder().get_page(cast(Browser, browser), pid=7) is first_page


def test_linux_page_finder_returns_none_when_no_pages_exist():
    browser = SimpleNamespace(contexts=[SimpleNamespace(pages=[]), SimpleNamespace(pages=[])])

    assert LinuxPageFinder().get_page(cast(Browser, browser), pid=7) is None


@pytest.mark.parametrize("finder_page", [None, SimpleNamespace(is_closed=lambda: True)])
def test_sync_page_restarts_browser_when_no_live_page_is_found(monkeypatch, finder_page):
    new_page = SimpleNamespace(is_closed=lambda: False)
    old_browser = SimpleNamespace(is_connected=lambda: True)
    new_browser = SimpleNamespace(
        is_connected=lambda: True,
        contexts=[SimpleNamespace(pages=[], new_page=lambda: new_page)],
    )
    new_state = SimpleNamespace(port=2, type="chromium", pid=43)
    class StaticFinder:
        def get_page(self, browser: Browser, pid: int) -> Page | None:
            return cast(Page | None, finder_page)

    finder = StaticFinder()
    fetched_browsers = iter([old_browser, new_browser])
    restart_calls = []
    monkeypatch.setattr(
        browser_runner,
        "get_execution_state",
        lambda _info: SimpleNamespace(port=1, type="chromium", pid=42),
    )
    monkeypatch.setattr(browser_runner, "sync_playwright", lambda: nullcontext(None))
    monkeypatch.setattr(browser_runner, "_fetch_browser", lambda *_args, **_kwargs: next(fetched_browsers))
    monkeypatch.setattr(browser_runner, "restart_browser", lambda info: restart_calls.append(info) or new_state)

    with browser_runner.sync_page(page_finder=finder) as page:
        assert page is new_page
    assert restart_calls == [None]


def test_sync_page_reconnects_when_browser_disconnects_during_page_lookup(monkeypatch):
    first_connection = {"connected": True}
    first_browser = SimpleNamespace(is_connected=lambda: first_connection["connected"])
    second_browser = SimpleNamespace(is_connected=lambda: True)
    disconnected_page = SimpleNamespace(is_closed=lambda: False)
    active_page = SimpleNamespace(is_closed=lambda: False)
    fetched_browsers = iter([first_browser, second_browser])

    class DisconnectingFinder:
        calls = 0

        def get_page(self, browser: Browser, pid: int) -> Page | None:
            self.calls += 1
            if browser is first_browser:
                first_connection["connected"] = False
                return cast(Page, disconnected_page)
            return cast(Page, active_page)

    finder = DisconnectingFinder()
    monkeypatch.setattr(
        browser_runner, "get_execution_state", lambda _info: SimpleNamespace(port=1, type="chromium", pid=42)
    )
    monkeypatch.setattr(browser_runner, "sync_playwright", lambda: nullcontext(None))
    monkeypatch.setattr(browser_runner, "_fetch_browser", lambda *_args, **_kwargs: next(fetched_browsers))

    with browser_runner.sync_page(page_finder=finder) as page:
        assert page is active_page
    assert finder.calls == 2


def test_fallback_page_reuses_first_page_from_existing_context():
    existing_page = object()
    context = SimpleNamespace(pages=[existing_page], new_page=lambda: object())
    browser = SimpleNamespace(contexts=[context])

    assert browser_runner._fallback_page(cast(Browser, browser), logging.getLogger()) is existing_page


def test_fallback_page_creates_page_in_existing_context():
    created_page = object()
    context = SimpleNamespace(pages=[], new_page=lambda: created_page)
    browser = SimpleNamespace(contexts=[context])

    assert browser_runner._fallback_page(cast(Browser, browser), logging.getLogger()) is created_page


def test_fallback_page_raises_when_browser_has_no_contexts():
    browser = SimpleNamespace(contexts=[])

    with pytest.raises(RuntimeError, match="No context found in the browser"):
        browser_runner._fallback_page(cast(Browser, browser), logging.getLogger())


def test_get_browser_pid_by_debug_port_finds_linux_chromium(monkeypatch):
    processes = [
        SimpleNamespace(
            info={
                "pid": 42,
                "name": "chromium",
                "cmdline": ["/usr/bin/chromium", "--remote-debugging-port=13456"],
            }
        ),
        SimpleNamespace(
            info={
                "pid": 43,
                "name": "chromium",
                "cmdline": ["/usr/bin/chromium", "--remote-debugging-port=13456", "--type=renderer"],
            }
        ),
    ]
    monkeypatch.setattr(launcher.psutil, "process_iter", lambda attrs: processes)

    assert launcher._get_browser_pid_by_debug_port(13456, "chromium") == 42


def test_get_browser_pid_by_debug_port_accepts_linux_chrome_executable_path(monkeypatch):
    processes = [
        SimpleNamespace(
            info={
                "pid": 84,
                "name": "chrome",
                "cmdline": ["/opt/google/chrome/chrome", "--remote-debugging-port=13457"],
            }
        )
    ]
    monkeypatch.setattr(launcher.psutil, "process_iter", lambda attrs: processes)

    assert launcher._get_browser_pid_by_debug_port(13457, "chromium") == 84
