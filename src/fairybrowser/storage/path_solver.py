import os
import platform
from pathlib import Path

from fairybrowser.models import BrowserType, SpawnType


class StoragePathSolver:
    def __init__(self, *, home_directory: Path | None = None, data_home: Path | None = None) -> None:
        self._home_directory = Path(home_directory) if home_directory is not None else Path.home()
        self._data_home = Path(data_home) if data_home is not None else self._default_data_home()

    def application_data_directory(self) -> Path:
        return self._data_home / "fairybrowser"

    def execution_states_directory(self) -> Path:
        return self.application_data_directory() / "execution_states"

    def browser_profile_directory(self, browser_type: BrowserType, spawn: SpawnType, name: str) -> Path:
        return self.application_data_directory() / "profiles" / f"{browser_type}_{spawn}" / name

    def invocation_plugins_directory(self) -> Path:
        return self.application_data_directory() / "invocations"

    def _default_data_home(self) -> Path:
        if platform.system() == "Windows":
            return Path(os.environ.get("LOCALAPPDATA") or self._home_directory / "AppData" / "Local")
        if platform.system() == "Darwin":
            return self._home_directory / "Library" / "Application Support"
        return Path(os.environ.get("XDG_DATA_HOME") or self._home_directory / ".local" / "share")
