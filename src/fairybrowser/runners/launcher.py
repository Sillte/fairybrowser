import subprocess
import time
from pathlib import Path

import psutil
from playwright.sync_api import sync_playwright

from fairybrowser.models import BrowserInfo, BrowserType, ExecutionState
from fairybrowser.monitors import save_state
from fairybrowser.port_utils import can_connect_port, find_available_port
from fairybrowser.storage import StoragePathSolver

_storage_path_solver = StoragePathSolver()


def _wait_for_port(port: int, host: str = "127.0.0.1", timeout: float = 10.0) -> None:
    start = time.time()
    while time.time() - start < timeout:
        if can_connect_port(port, host):
            return
        time.sleep(0.1)
    raise TimeoutError(f"Port {port} did not open within {timeout} seconds.")


def _get_browser_pid_by_debug_port(port: int, browser_type: BrowserType) -> int:
    target_arg = f"--remote-debugging-port={port}"
    browser_names = {
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
    candidates: list[int] = []

    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            name = (proc.info["name"] or "").lower()
            cmdline = proc.info["cmdline"] or []
            executable_name = Path(cmdline[0]).name.lower() if cmdline else ""
            if name not in browser_names and executable_name not in browser_names:
                continue
            if target_arg not in cmdline:
                continue

            if any(arg.startswith("--type=") for arg in cmdline):
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
        for option in options:
            browser_options.add_argument(option)
        webdriver.Edge(options=browser_options)
    elif info.type == "chromium":
        from selenium.webdriver.chrome.options import Options

        browser_options = Options()
        browser_options.add_experimental_option("detach", True)
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
    start_port = 13456 if info.type == "chromium" else 18456
    port = find_available_port(start=start_port)
    print("port", port)

    default_options = [
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-infobars",
    ]
    user_dir = _storage_path_solver.browser_profile_directory(info.type, info.spawn, info.name)
    options = [
        f"--user-data-dir={user_dir}",
        *default_options,
    ]
    if info.spawn == "webdriver":
        execution_info = _run_web_driver(port, info, options)
    elif info.spawn == "popen":
        execution_info = _run_exe(port, info, options)
    else:
        raise ValueError("Invalid `BrowserInfo.spawn`.")
    save_state(execution_info)
    _wait_for_port(port)
    return execution_info
