from pathlib import Path
import json
import os
import psutil


from playwright.sync_api import BrowserContext
from fairybrowser.models import BrowserInfo, ExecutionInfo
from fairybrowser.port_utils import is_port_free


_this_folder = Path(__file__).absolute().parent
_states_folder = _this_folder / "EXECUTION_STATES"
_states_folder.mkdir(exist_ok=True)


def save_state(info: ExecutionInfo) -> None:
    path = _states_folder / f"{info.name}.json"
    path.write_text(info.model_dump_json())


def load_state(name: str) -> ExecutionInfo:
    path = _states_folder / f"{name}.json"
    return ExecutionInfo.model_validate_json(path.read_text())


def get_execution_infos() -> dict[str, ExecutionInfo]:
    result = {}
    for path in _states_folder.glob("*.json"):
        key = path.stem
        model = ExecutionInfo.model_validate_json(path.read_text())
        if is_pid_alive(model.pid) and (not is_port_free(model.port)):
            result[key] = model
    return result


def to_browser_info(info: BrowserInfo | str | None = None) -> BrowserInfo:
    if info is None:
        info = BrowserInfo()
    elif isinstance(info, str):
        info = BrowserInfo(name=info)
    assert isinstance(info, BrowserInfo)
    return info


def get_pid(browser_info: BrowserInfo | str | None = None) -> int | None:
    browser_info = to_browser_info(browser_info)
    for path in _states_folder.glob("*.json"):
        data = json.loads(path.read_text())
        if data["name"] == browser_info.name:
            return data["pid"]
    return None


def is_pid_alive(pid: int) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        return psutil.pid_exists(pid)
    except Exception:
        # アクセス権限がない場合は True とする
        return True


def is_existent(name: str) -> bool:
    path = _states_folder / f"{name}.json"
    if not path.exists():
        return False
    try:
        model = ExecutionInfo.model_validate_json(path.read_text())
    except Exception:
        return False
    return is_pid_alive(model.pid) and (not is_port_free(model.port))
