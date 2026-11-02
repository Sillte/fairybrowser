from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from fairybrowser.models import BrowserInfo, ExecutionState
from fairybrowser.runners import browser as runner_browser
from fairybrowser.runners import launcher
from fairybrowser.storage import StoragePathSolver


@pytest.fixture
def isolated_launcher(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "_storage_path_solver", StoragePathSolver(data_home=tmp_path))


def _process(pid: int, cmdline: list[str]):
    return SimpleNamespace(
        info={"pid": pid, "name": "chrome.exe", "cmdline": cmdline},
    )


def test_state_from_profile_process_recovers_existing_debuggable_browser(isolated_launcher, monkeypatch):
    info = BrowserInfo(name="existing")
    user_dir = launcher._profile_directory(info)
    process = _process(
        42,
        ["C:\\Program Files\\Chrome\\chrome.exe", f"--user-data-dir={user_dir}", "--remote-debugging-port=9321"],
    )
    monkeypatch.setattr(launcher.psutil, "process_iter", lambda attrs: [process])

    state = launcher._state_from_profile_process(info, user_dir)

    assert state == ExecutionState(name="existing", type="chromium", port=9321, pid=42)


def test_state_from_profile_process_raises_if_profile_browser_has_no_debug_port(isolated_launcher, monkeypatch):
    info = BrowserInfo(name="existing")
    user_dir = launcher._profile_directory(info)
    process = _process(42, ["chrome.exe", f"--user-data-dir={user_dir}"])
    monkeypatch.setattr(launcher.psutil, "process_iter", lambda attrs: [process])

    with pytest.raises(RuntimeError, match="no process has a remote debugging port"):
        launcher._state_from_profile_process(info, user_dir)


def test_state_from_profile_process_ignores_processes_without_debug_ports(isolated_launcher, monkeypatch):
    info = BrowserInfo(name="existing")
    user_dir = launcher._profile_directory(info)
    processes = [
        _process(42, ["chrome.exe", f"--user-data-dir={user_dir}"]),
        _process(43, ["chrome.exe", f"--user-data-dir={user_dir}", "--remote-debugging-port=9321"]),
    ]
    monkeypatch.setattr(launcher.psutil, "process_iter", lambda attrs: processes)

    state = launcher._state_from_profile_process(info, user_dir)

    assert state == ExecutionState(name="existing", type="chromium", port=9321, pid=43)


def test_state_from_profile_process_raises_for_multiple_debug_port_candidates(isolated_launcher, monkeypatch):
    info = BrowserInfo(name="existing")
    user_dir = launcher._profile_directory(info)
    processes = [
        _process(42, ["chrome.exe", f"--user-data-dir={user_dir}", "--remote-debugging-port=9321"]),
        _process(43, ["chrome.exe", f"--user-data-dir={user_dir}", "--remote-debugging-port=9322"]),
    ]
    monkeypatch.setattr(launcher.psutil, "process_iter", lambda attrs: processes)

    with pytest.raises(RuntimeError, match="Multiple browser processes have remote debugging ports"):
        launcher._state_from_profile_process(info, user_dir)


def test_run_chromium_reuses_profile_process_and_saves_recovered_state(
    isolated_launcher, monkeypatch
):
    info = BrowserInfo(name="existing")
    user_dir = launcher._profile_directory(info)
    process = _process(
        42,
        ["chrome.exe", f"--user-data-dir={user_dir}", "--remote-debugging-port=9321"],
    )
    saved = Mock()
    monkeypatch.setattr(launcher.psutil, "process_iter", lambda attrs: [process])
    monkeypatch.setattr(launcher, "_wait_for_port", lambda port: None)
    monkeypatch.setattr(launcher, "_is_browser_fetchable", lambda port: True)
    monkeypatch.setattr(launcher, "save_state", saved)
    monkeypatch.setattr(
        launcher,
        "_run_web_driver",
        lambda *args: pytest.fail("must not start another browser for an active profile"),
    )

    state = launcher._run_chromium(info)

    assert state == ExecutionState(name="existing", type="chromium", port=9321, pid=42)
    saved.assert_called_once_with(state)


def test_run_chromium_does_not_save_unreachable_profile_process(isolated_launcher, monkeypatch):
    info = BrowserInfo(name="existing")
    user_dir = launcher._profile_directory(info)
    process = _process(
        42,
        ["chrome.exe", f"--user-data-dir={user_dir}", "--remote-debugging-port=9321"],
    )
    saved = Mock()
    monkeypatch.setattr(launcher.psutil, "process_iter", lambda attrs: [process])
    monkeypatch.setattr(launcher, "_wait_for_port", lambda port: None)
    monkeypatch.setattr(launcher, "_is_browser_fetchable", lambda port: False)
    monkeypatch.setattr(launcher, "save_state", saved)

    with pytest.raises(RuntimeError, match="debugging endpoint is unavailable"):
        launcher._run_chromium(info)

    saved.assert_not_called()


def test_execution_state_must_match_profile_and_port(monkeypatch, tmp_path):
    user_dir = tmp_path / "profile"
    state = ExecutionState(name="existing", type="chromium", port=9321, pid=42)
    process = SimpleNamespace(
        name=lambda: "chrome.exe",
        cmdline=lambda: [
            "chrome.exe",
            f"--user-data-dir={user_dir}",
            "--remote-debugging-port=9322",
        ],
    )
    monkeypatch.setattr(launcher.psutil, "Process", lambda pid: process)

    assert not launcher._is_execution_state_for_profile(state, user_dir)


def test_process_uses_profile_resolves_paths_and_supports_split_arguments(tmp_path):
    user_dir = tmp_path / "profile"
    equivalent_user_dir = user_dir / ".." / "profile"
    cmdline = ["chrome.exe", "--user-data-dir", str(equivalent_user_dir)]

    assert launcher._process_uses_profile(cmdline, user_dir)


def test_profile_argument_without_path_does_not_match(tmp_path):
    assert not launcher._process_uses_profile(["chrome.exe"], Path(tmp_path))


def test_cached_execution_state_for_another_profile_is_not_reused(monkeypatch, tmp_path):
    info = BrowserInfo(name="requested")
    cached_state = ExecutionState(name="requested", type="chromium", port=9321, pid=42)
    launched_state = ExecutionState(name="requested", type="chromium", port=9322, pid=43)
    monkeypatch.setattr(runner_browser, "is_existent", lambda browser_info: True)
    monkeypatch.setattr(runner_browser, "load_state", lambda browser_info: cached_state)
    monkeypatch.setattr(runner_browser, "_profile_directory", lambda browser_info: tmp_path / "requested")
    monkeypatch.setattr(runner_browser, "_is_execution_state_for_profile", lambda state, user_dir: False)
    monkeypatch.setattr(runner_browser, "_run_chromium", lambda browser_info: launched_state)

    assert runner_browser._to_apt_execution_state(info) == launched_state
