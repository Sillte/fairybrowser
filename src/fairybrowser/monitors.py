from pathlib import Path
import psutil


from fairybrowser.models import BrowserInfo, ExecutionState, BrowserTypeEnum
from fairybrowser.port_utils import is_port_free


_this_folder = Path(__file__).absolute().parent
_states_folder = _this_folder / "EXECUTION_STATES"
_states_folder.mkdir(exist_ok=True)


def _to_type_folder(type: BrowserTypeEnum) -> Path:
    return _states_folder / type


def _to_json_path(name: str, type: BrowserTypeEnum) -> Path:
    return _to_type_folder(type) / f"{name}.json"


def save_state(state: ExecutionState) -> None:
    path = _to_json_path(state.name, state.type)
    path.parent.mkdir(exist_ok=True)
    path.write_text(state.model_dump_json())


def load_state(info: BrowserInfo) -> ExecutionState:
    path = _to_json_path(info.name, info.type)
    return ExecutionState.model_validate_json(path.read_text())


def is_existent(info: BrowserInfo) -> bool:
    path = _to_json_path(info.name, info.type)
    if not path.exists():
        return False
    try:
        model = ExecutionState.model_validate_json(path.read_text())
    except Exception:
        path.unlink()
        return False
    result = is_pid_alive(model.pid) and (not is_port_free(model.port))
    if not result:
        path.unlink()
    return result


def get_execution_infos() -> dict[BrowserInfo, ExecutionState]:
    result = {}
    for path in _states_folder.glob("*/*.json"):
        type = path.parent.stem
        name = path.stem
        type_enum = BrowserTypeEnum(type)  # More thorough check is desired.
        info = BrowserInfo(name=name, type=type_enum)
        model = ExecutionState.model_validate_json(path.read_text())
        if is_pid_alive(model.pid) and (not is_port_free(model.port)):
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
