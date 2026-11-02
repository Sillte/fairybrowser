import hashlib
import logging
import os
import subprocess
import time
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

import psutil
from playwright.sync_api import sync_playwright

from fairybrowser.models import BrowserInfo, BrowserType, ExecutionState
from fairybrowser.monitors import (
    _is_browser_fetchable,
    get_execution_infos,
    is_existent,
    load_state,
    save_state,
    to_browser_info,
)
from fairybrowser.port_utils import can_connect_port, find_available_port
from fairybrowser.storage import StoragePathSolver

logger = logging.getLogger(__name__)
_storage_path_solver = StoragePathSolver()


def _browser_names(browser_type: BrowserType) -> set[str]:
    return {
        "chromium": {
            "chrome",
            "chrome.exe",
            "chromium",
            "chromium-browser",
            "google-chrome",
            "google-chrome-stable",
        },
        "edge": {"msedge", "msedge.exe", "microsoft-edge", "microsoft-edge-stable"},
    }[browser_type]


def _is_browser_process(name: str, cmdline: list[str], browser_type: BrowserType) -> bool:
    names = _browser_names(browser_type)
    executable_name = Path(cmdline[0]).name.lower() if cmdline else ""
    return (
        (name.lower() in names or executable_name in names)
        and not any(arg.startswith("--type=") for arg in cmdline)
    )


def _argument_value(cmdline: list[str], name: str) -> str | None:
    prefix = f"{name}="
    for index, arg in enumerate(cmdline):
        if arg.startswith(prefix):
            return arg[len(prefix) :]
        if arg == name and index + 1 < len(cmdline):
            return cmdline[index + 1]
    return None


def _normalized_path(path: str | Path) -> str:
    return os.path.normcase(str(Path(path).resolve()))


def _profile_directory(info: BrowserInfo) -> Path:
    return _storage_path_solver.browser_profile_directory(info.type, info.spawn, info.name)


def _process_uses_profile(cmdline: list[str], user_dir: Path) -> bool:
    process_user_dir = _argument_value(cmdline, "--user-data-dir")
    return process_user_dir is not None and _normalized_path(process_user_dir) == _normalized_path(user_dir)


def _debug_port(cmdline: list[str]) -> int | None:
    value = _argument_value(cmdline, "--remote-debugging-port")
    if value is None:
        return None
    try:
        port = int(value)
    except ValueError:
        return None
    return port if 1 <= port <= 65535 else None


def _get_browser_processes_by_profile(
    user_dir: Path, browser_type: BrowserType
) -> list[tuple[int, list[str]]]:
    matches = []
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            name = proc.info["name"] or ""
            cmdline = proc.info["cmdline"] or []
            if (
                _is_browser_process(name, cmdline, browser_type)
                and _process_uses_profile(cmdline, user_dir)
            ):
                matches.append((proc.info["pid"], cmdline))
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    return matches


def _is_execution_state_for_profile(state: ExecutionState, user_dir: Path) -> bool:
    try:
        proc = psutil.Process(state.pid)
        name = proc.name()
        cmdline = proc.cmdline()
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return False
    return (
        _is_browser_process(name, cmdline, state.type)
        and _process_uses_profile(cmdline, user_dir)
        and _debug_port(cmdline) == state.port
    )


def _is_execution_state_process(state: ExecutionState) -> bool:
    try:
        proc = psutil.Process(state.pid)
        name = proc.name()
        cmdline = proc.cmdline()
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return False
    return _is_browser_process(name, cmdline, state.type) and _debug_port(cmdline) == state.port


def _state_from_profile_process(
    info: BrowserInfo, user_dir: Path
) -> ExecutionState | None:
    processes = _get_browser_processes_by_profile(user_dir, info.type)
    if not processes:
        return None
    candidates = [(pid, port) for pid, cmdline in processes if (port := _debug_port(cmdline)) is not None]
    if not candidates:
        raise RuntimeError(
            f"A browser is already using profile {user_dir}, but no process has a remote debugging port."
        )
    if len(candidates) > 1:
        raise RuntimeError(
            f"Multiple browser processes have remote debugging ports for profile {user_dir}: {candidates}"
        )

    pid, port = candidates[0]
    return ExecutionState(name=info.name, type=info.type, port=port, pid=pid)


@contextmanager
def _profile_lock(user_dir: Path) -> Generator[None, None, None]:
    lock_name = hashlib.sha256(_normalized_path(user_dir).encode()).hexdigest()
    lock_path = _storage_path_solver.application_data_directory() / "profile_locks" / f"{lock_name}.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as lock_file:
        if os.name == "nt":
            import msvcrt

            lock_file.seek(0, os.SEEK_END)
            if lock_file.tell() == 0:
                lock_file.write(b"\0")
                lock_file.flush()
            deadline = time.monotonic() + 30
            while True:
                try:
                    lock_file.seek(0)
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError(f"Timed out waiting for the browser profile lock: {user_dir}")
                    time.sleep(0.1)
            try:
                yield
            finally:
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _wait_for_port(port: int, host: str = "127.0.0.1", timeout: float = 10.0) -> None:
    start = time.time()
    while time.time() - start < timeout:
        if can_connect_port(port, host):
            return
        time.sleep(0.1)
    raise TimeoutError(f"Port {port} did not open within {timeout} seconds.")


def _get_browser_pid_by_debug_port(port: int, browser_type: BrowserType) -> int:
    target_arg = f"--remote-debugging-port={port}"
    candidates: list[int] = []

    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            name = (proc.info["name"] or "").lower()
            cmdline = proc.info["cmdline"] or []
            if not _is_browser_process(name, cmdline, browser_type):
                continue
            if _debug_port(cmdline) != port:
                continue

            candidates.append(proc.info["pid"])

        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise ValueError(f"No browser process found for {target_arg}.")
    raise ValueError(f"Multiple browser processes found for {target_arg}: {candidates}")


def _run_web_driver(port: int, info: BrowserInfo, options: list[str]) -> ExecutionState:
    options = [*options, f"--remote-debugging-port={port}"]
    from selenium import webdriver

    if info.type == "edge":
        from selenium.webdriver.edge.options import Options

        browser_options = Options()
        browser_options.add_experimental_option("detach", True)
        browser_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        for option in options:
            browser_options.add_argument(option)
        webdriver.Edge(options=browser_options)
    elif info.type == "chromium":
        from selenium.webdriver.chrome.options import Options

        browser_options = Options()
        browser_options.add_experimental_option("detach", True)
        browser_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        for option in options:
            browser_options.add_argument(option)
        webdriver.Chrome(options=browser_options)
    else:
        raise ValueError("Invalid Type", info)

    pid = _get_browser_pid_by_debug_port(port, info.type)
    return ExecutionState(name=info.name, pid=pid, type=info.type, port=port)


def _get_edge_path() -> Path:
    possible_paths = [
        Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"),
        Path("C:/Program Files/Microsoft/Edge/Application/msedge.exe"),
    ]
    for path in possible_paths:
        if path.exists():
            return path
    raise FileNotFoundError("Microsoft Edge executable not found.")


def _get_chromium_path() -> Path:
    with sync_playwright() as playwright:
        chromium_path = playwright.chromium.executable_path
    return Path(chromium_path)


def _run_exe(port: int, info: BrowserInfo, options: list[str]) -> ExecutionState:
    if info.type == "edge":
        path = _get_edge_path()
    elif info.type == "chromium":
        path = _get_chromium_path()
    else:
        raise ValueError(f"InvalidInfo, {info=}")

    options = [*options, f"--remote-debugging-port={port}"]
    process = subprocess.Popen([str(path), *options])
    time.sleep(0.3)
    return ExecutionState(name=info.name, pid=process.pid, type=info.type, port=port)


def _run_chromium(info: BrowserInfo) -> ExecutionState:
    """Run a Chromium-based browser and wait for its debugging port."""
    user_dir = _profile_directory(info)
    with _profile_lock(user_dir):
        execution_info = _state_from_profile_process(info, user_dir)
        if execution_info is not None:
            _wait_for_port(execution_info.port)
            if not _is_browser_fetchable(execution_info.port):
                raise RuntimeError(
                    f"A browser is using profile {user_dir}, but its debugging endpoint is unavailable."
                )
            save_state(execution_info)
            return execution_info
        start_port = 13456 if info.type == "chromium" else 18456
        port = find_available_port(start=start_port)
        logger.debug("Selected browser debugging port: %s", port)

        default_options = [
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-infobars",
        ]
        options = [
            f"--user-data-dir={user_dir}",
            *default_options,
        ]
        if info.spawn == "webdriver":
            _run_web_driver(port, info, options)
        elif info.spawn == "popen":
            _run_exe(port, info, options)
        else:
            raise ValueError("Invalid `BrowserInfo.spawn`.")

        _wait_for_port(port)
        pid = _get_browser_pid_by_debug_port(port, info.type)
        execution_info = ExecutionState(name=info.name, pid=pid, type=info.type, port=port)
        if not _is_execution_state_for_profile(execution_info, user_dir):
            raise RuntimeError(
                f"The browser started for profile {user_dir} does not match its process or debugging port."
            )
        if not _is_browser_fetchable(port):
            raise RuntimeError(f"The debugging endpoint for profile {user_dir} is unavailable.")
        save_state(execution_info)
        return execution_info


def get_execution_state(info: BrowserInfo | str | None = None) -> ExecutionState:
    """Return a validated managed-browser state, starting the requested profile if needed."""
    if info is not None:
        browser_info = to_browser_info(info)
        user_dir = _profile_directory(browser_info)
        if is_existent(browser_info):
            state = load_state(browser_info)
            if _is_execution_state_for_profile(state, user_dir):
                return state
        return _run_chromium(browser_info)

    for state in get_execution_infos().values():
        if _is_execution_state_process(state):
            return state
    return _run_chromium(to_browser_info())
