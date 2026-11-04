import json
import logging
import urllib.request
from pathlib import Path

import psutil

from fairybrowser.models import BrowserInfo, BrowserType, ExecutionState
from fairybrowser.storage import StoragePathSolver

logger = logging.getLogger(__name__)
_storage_path_solver = StoragePathSolver()


def _to_type_folder(type: BrowserType) -> Path:
    return _storage_path_solver.execution_states_directory() / type


def _to_json_path(name: str, type: BrowserType) -> Path:
    return _to_type_folder(type) / f"{name}.json"


def _legacy_json_paths(info: BrowserInfo) -> list[Path]:
    if info.type == "chrome":
        return [_storage_path_solver.execution_states_directory() / "chromium" / f"{info.name}.json"]
    return []


def save_state(state: ExecutionState) -> None:
    path = _to_json_path(state.name, state.type)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(state.model_dump_json())


def load_state(info: BrowserInfo) -> ExecutionState:
    path = next(
        (candidate for candidate in [_to_json_path(info.name, info.type), *_legacy_json_paths(info)] if candidate.exists()),
        _to_json_path(info.name, info.type),
    )
    state = ExecutionState.model_validate_json(path.read_text())
    if path != _to_json_path(info.name, info.type):
        save_state(state)
    return state


def _is_alive(execution_state: ExecutionState) -> bool:
    return is_pid_alive(execution_state.pid) and _is_browser_fetchable(execution_state.port)


def is_existent(info: BrowserInfo) -> bool:
    paths = [_to_json_path(info.name, info.type), *_legacy_json_paths(info)]
    path = next((candidate for candidate in paths if candidate.exists()), None)
    if path is None:
        return False
    try:
        model = ExecutionState.model_validate_json(path.read_text())
    except Exception:
        path.unlink()
        return False
    if _is_alive(model):
        if path != paths[0]:
            save_state(model)
        return True
    path.unlink()
    return False


def get_execution_infos() -> dict[BrowserInfo, ExecutionState]:
    result = {}
    for path in _storage_path_solver.execution_states_directory().glob("*/*.json"):
        state_type = path.parent.stem
        name = path.stem
        if state_type == "chromium":
            browser_type = "chrome"
        elif state_type in {"chrome", "edge"}:
            browser_type = state_type
        else:
            raise ValueError(f"`{state_type=}` is not appropriate.")
        info = BrowserInfo(name=name, type=browser_type)
        model = ExecutionState.model_validate_json(path.read_text())
        if _is_alive(model):
            if path.parent.stem == "chromium":
                if info not in result:
                    result[info] = model
                    save_state(model)
            else:
                result[info] = model
        else:
            path.unlink()
    return result


def to_browser_info(info: BrowserInfo | str | None = None) -> BrowserInfo:
    """To browser_info. If `str` is given, it is regarded as the name."""
    if info is None:
        info = BrowserInfo()
    elif isinstance(info, str):
        info = BrowserInfo(name=info)
    assert isinstance(info, BrowserInfo)
    return info


def get_pid(browser_info: BrowserInfo | str | None = None) -> int | None:
    browser_info = to_browser_info(browser_info)
    pair_to_info = get_execution_infos()
    for _, info in pair_to_info.items():
        if info.name == browser_info.name and info.type == browser_info.type:
            return info.pid
    return None


def is_pid_alive(pid: int) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        return psutil.pid_exists(pid)
    except Exception:
        # アクセス権限がない場合は True とする
        return True


def _is_browser_fetchable(port: int) -> bool:
    url = f"http://localhost:{port}/json/version"
    try:
        with urllib.request.urlopen(url, timeout=1.0) as response:
            if response.status != 200:
                return False
            version_info = json.loads(response.read().decode())
    except Exception:
        logger.debug("Failed to fetch browser debugging endpoint %s", url, exc_info=True)
        return False
    return isinstance(version_info, dict) and bool(
        version_info.get("Browser") and version_info.get("webSocketDebuggerUrl")
    )
