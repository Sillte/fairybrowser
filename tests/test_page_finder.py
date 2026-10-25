from contextlib import nullcontext
from types import SimpleNamespace

from fairybrowser.page_finder import create_page_finder, windows
from fairybrowser.page_finder.linux import LinuxPageFinder
from fairybrowser.runners import browser as runner_browser
from fairybrowser.runners import launcher, sync_page


def test_windows_page_finder_selects_page_matching_visible_browser_window(monkeypatch):
    selected_page = SimpleNamespace(title=lambda: "Example")
    context = SimpleNamespace(
        pages=[selected_page],
        new_cdp_session=lambda page: SimpleNamespace(
            send=lambda command: {"bounds": {"windowState": "maximized"}}
        ),
    )
    browser = SimpleNamespace(contexts=[context])
    process = SimpleNamespace(children=lambda recursive: [SimpleNamespace(pid=42)])

    monkeypatch.setattr(windows.psutil, "Process", lambda: process)
    monkeypatch.setattr(
        windows,
        "get_visible_windows",
        lambda: [SimpleNamespace(pid=42, title="Example - Browser")],
    )

    assert windows.WindowsPageFinder().get_page(browser, pid=7) is selected_page


def test_linux_page_finder_returns_the_first_page_across_contexts():
    first_page = object()
    browser = SimpleNamespace(
        contexts=[
            SimpleNamespace(pages=[first_page, object()]),
            SimpleNamespace(pages=[object()]),
        ]
    )

    assert LinuxPageFinder().get_page(browser, pid=7) is first_page


def test_linux_page_finder_returns_none_when_no_pages_exist():
    browser = SimpleNamespace(contexts=[SimpleNamespace(pages=[]), SimpleNamespace(pages=[])])

    assert LinuxPageFinder().get_page(browser, pid=7) is None


def test_create_page_finder_returns_platform_implementation(monkeypatch):
    monkeypatch.setattr("fairybrowser.page_finder.sys.platform", "linux")

    assert isinstance(create_page_finder(), LinuxPageFinder)


def test_create_page_finder_returns_windows_implementation(monkeypatch):
    monkeypatch.setattr("fairybrowser.page_finder.sys.platform", "win32")

    assert isinstance(create_page_finder(), windows.WindowsPageFinder)


def test_sync_page_uses_injected_page_finder(monkeypatch):
    state = SimpleNamespace(port=1234, type="chromium", pid=7)
    browser = object()
    selected_page = object()
    finder = SimpleNamespace(get_page=lambda actual_browser, pid: selected_page)

    monkeypatch.setattr(runner_browser, "_to_apt_execution_state", lambda browser_info: state)
    monkeypatch.setattr(runner_browser, "sync_playwright", lambda: nullcontext(object()))
    monkeypatch.setattr(runner_browser, "_fetch_browser", lambda *args, **kwargs: browser)

    with sync_page(page_finder=finder) as page:
        assert page is selected_page


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
