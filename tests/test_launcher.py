from pathlib import Path
from types import SimpleNamespace

import pytest

from fairybrowser.models import BrowserInfo, ExecutionState
from fairybrowser.runners import launcher


def _process(pid: int, cmdline: list[str]):
    return SimpleNamespace(
        info={"pid": pid, "name": "chrome.exe", "cmdline": cmdline},
    )


def test_state_from_profile_process_recovers_existing_debuggable_browser(tmp_path, monkeypatch):
    info = BrowserInfo(name="existing")
    user_dir = tmp_path / "existing-profile"
    process = _process(
        42,
        ["C:\\Program Files\\Chrome\\chrome.exe", f"--user-data-dir={user_dir}", "--remote-debugging-port=9321"],
    )
    monkeypatch.setattr(launcher.psutil, "process_iter", lambda attrs: [process])

    state = launcher._state_from_profile_process(info, user_dir)

    assert state == ExecutionState(name="existing", type="chromium", port=9321, pid=42)


def test_state_from_profile_process_raises_if_profile_browser_has_no_debug_port(tmp_path, monkeypatch):
    info = BrowserInfo(name="existing")
    user_dir = tmp_path / "existing-profile"
    process = _process(42, ["chrome.exe", f"--user-data-dir={user_dir}"])
    monkeypatch.setattr(launcher.psutil, "process_iter", lambda attrs: [process])

    with pytest.raises(RuntimeError, match="no process has a remote debugging port"):
        launcher._state_from_profile_process(info, user_dir)


def test_state_from_profile_process_ignores_processes_without_debug_ports(tmp_path, monkeypatch):
    info = BrowserInfo(name="existing")
    user_dir = tmp_path / "existing-profile"
    processes = [
        _process(42, ["chrome.exe", f"--user-data-dir={user_dir}"]),
        _process(43, ["chrome.exe", f"--user-data-dir={user_dir}", "--remote-debugging-port=9321"]),
    ]
    monkeypatch.setattr(launcher.psutil, "process_iter", lambda attrs: processes)

    state = launcher._state_from_profile_process(info, user_dir)

    assert state == ExecutionState(name="existing", type="chromium", port=9321, pid=43)


def test_state_from_profile_process_raises_for_multiple_debug_port_candidates(tmp_path, monkeypatch):
    info = BrowserInfo(name="existing")
    user_dir = tmp_path / "existing-profile"
    processes = [
        _process(42, ["chrome.exe", f"--user-data-dir={user_dir}", "--remote-debugging-port=9321"]),
        _process(43, ["chrome.exe", f"--user-data-dir={user_dir}", "--remote-debugging-port=9322"]),
    ]
    monkeypatch.setattr(launcher.psutil, "process_iter", lambda attrs: processes)

    with pytest.raises(RuntimeError, match="Multiple browser processes have remote debugging ports"):
        launcher._state_from_profile_process(info, user_dir)


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
