import os
import platform
from pathlib import Path

from fairybrowser.models import BrowserType


class StoragePathSolver:
    def __init__(self, *, home_directory: Path | None = None, data_home: Path | None = None) -> None:
        self._home_directory = Path(home_directory) if home_directory is not None else Path.home()
        self._data_home = Path(data_home) if data_home is not None else self._default_data_home()

    def application_data_directory(self) -> Path:
        return self._data_home / "fairybrowser"

    def execution_states_directory(self) -> Path:
        return self.application_data_directory() / "execution_states"

    def browser_profile_directory(self, browser_type: BrowserType, name: str) -> Path:
        return self.application_data_directory() / "profiles" / browser_type / name

    def legacy_browser_profile_directories(self, browser_type: BrowserType, name: str) -> list[Path]:
        profiles_directory = self.application_data_directory() / "profiles"
        legacy_types: list[str] = [browser_type, "chromium"] if browser_type == "chrome" else [browser_type]
        directories = [
            profiles_directory / f"{legacy_type}_{mode}" / name
            for legacy_type in legacy_types
            for mode in ("webdriver", "auto", "direct", "popen")
        ]
        if browser_type == "chrome":
            directories.append(profiles_directory / "chromium" / name)
        return directories

    def invocation_plugins_directory(self) -> Path:
        return self.application_data_directory() / "invocations"

    def _default_data_home(self) -> Path:
        if platform.system() == "Windows":
            return Path(os.environ.get("LOCALAPPDATA") or self._home_directory / "AppData" / "Local")
        if platform.system() == "Darwin":
            return self._home_directory / "Library" / "Application Support"
        return Path(os.environ.get("XDG_DATA_HOME") or self._home_directory / ".local" / "share")
