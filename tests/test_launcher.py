from pathlib import Path
from types import SimpleNamespace

import pytest

from fairybrowser.models import BrowserInfo, ExecutionState
from fairybrowser.runners import launcher


def _process(pid: int, cmdline: list[str]):
    return SimpleNamespace(
        info={"pid": pid, "name": "chrome.exe", "cmdline": cmdline},
    )


def test_terminate_debuggable_profile_processes_only_targets_matching_profile(tmp_path, monkeypatch):
    user_dir = tmp_path / "profile"
    other_dir = tmp_path / "other-profile"
    processes = [
        _process(42, ["chrome.exe", f"--user-data-dir={user_dir}", "--remote-debugging-port=9321"]),
        _process(43, ["chrome.exe", f"--user-data-dir={user_dir}"]),
        _process(44, ["chrome.exe", f"--user-data-dir={other_dir}", "--remote-debugging-port=9322"]),
        _process(45, ["chrome.exe", f"--user-data-dir={user_dir}", "--remote-debugging-port=9323", "--type=renderer"]),
    ]
    terminated = []

    class RunningProcess:
        def __init__(self, pid):
            self.pid = pid
            self.source = next(process for process in processes if process.info["pid"] == pid)

        def name(self):
            return self.source.info["name"]

        def cmdline(self):
            return self.source.info["cmdline"]

        def terminate(self):
            terminated.append(self.pid)

        def wait(self, timeout):
            return None

    monkeypatch.setattr(launcher.psutil, "process_iter", lambda attrs: processes)
    monkeypatch.setattr(launcher.psutil, "Process", RunningProcess)

    assert launcher._terminate_profile_processes(user_dir, "chromium", require_debug_port=True)
    assert terminated == [42]

    terminated.clear()
    assert launcher._terminate_profile_processes(user_dir, "chromium", require_debug_port=False)
    assert terminated == [42, 43]


def test_profile_lock_retries_after_terminating_matching_processes(tmp_path, monkeypatch):
    times = iter([0, 31, 31])
    attempts = []
    cleanup_calls = []

    def acquire_lock():
        attempts.append(None)
        if len(attempts) == 1:
            raise OSError("lock is held")

    monkeypatch.setattr(launcher.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(launcher.time, "sleep", lambda _: None)
    monkeypatch.setattr(
        launcher,
        "_terminate_profile_processes",
        lambda user_dir, browser_type, *, require_debug_port: (
            cleanup_calls.append((user_dir, browser_type, require_debug_port)) or True
        ),
    )

    launcher._acquire_profile_file_lock(tmp_path / "profile", "chromium", acquire_lock)

    assert len(attempts) == 2
    assert cleanup_calls == [(tmp_path / "profile", "chromium", True)]


def test_restart_browser_terminates_all_profile_processes_before_starting(monkeypatch, tmp_path):
    info = BrowserInfo(name="existing")
    user_dir = tmp_path / "existing-profile"
    expected_state = ExecutionState(name="existing", type="chromium", port=9321, pid=42)
    termination_calls = []
    monkeypatch.setattr(launcher, "_profile_directory", lambda browser_info: user_dir)
    monkeypatch.setattr(
        launcher,
        "_terminate_profile_processes",
        lambda path, browser_type, *, require_debug_port: (
            termination_calls.append((path, browser_type, require_debug_port)) or True
        ),
    )
    monkeypatch.setattr(launcher, "_get_browser_processes_by_profile", lambda *_args: [])
    monkeypatch.setattr(launcher, "_run_chromium", lambda browser_info: expected_state)

    assert launcher.restart_browser(info) == expected_state
    assert termination_calls == [(user_dir, "chromium", False)]


def test_find_alternate_execution_state_uses_same_profile_debug_port(tmp_path, monkeypatch):
    info = BrowserInfo(name="existing")
    user_dir = tmp_path / "existing-profile"
    processes = [
        _process(42, ["chrome.exe", f"--user-data-dir={user_dir}", "--remote-debugging-port=9321"]),
        _process(43, ["chrome.exe", f"--user-data-dir={user_dir}", "--remote-debugging-port=9322"]),
        _process(44, ["chrome.exe", f"--user-data-dir={tmp_path / 'other-profile'}", "--remote-debugging-port=9323"]),
        _process(46, ["chrome.exe", f"--user-data-dir={user_dir}", "--remote-debugging-port=9324"]),
        _process(45, ["chrome.exe", f"--user-data-dir={user_dir}"]),
    ]
    monkeypatch.setattr(launcher, "_profile_directory", lambda _info: user_dir)
    monkeypatch.setattr(launcher.psutil, "process_iter", lambda attrs: processes)

    state = launcher.find_alternate_execution_state(info, current_pid=42)

    assert state == [
        ExecutionState(name="existing", type="chromium", port=9322, pid=43),
        ExecutionState(name="existing", type="chromium", port=9324, pid=46),
    ]


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
