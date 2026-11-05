import hashlib
import importlib.util
import re
import sys
from pathlib import Path
from types import ModuleType

from fairybrowser.plugin.exceptions import PluginLoadError, PluginNotFoundError

_PLUGIN_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


class PluginModuleLoader:
    """Discover plugin modules and load their trusted Python code."""

    def __init__(self, plugin_directory: Path) -> None:
        self.plugin_directory = Path(plugin_directory).expanduser()

    def list_plugins(self) -> tuple[str, ...]:
        if not self.plugin_directory.is_dir():
            return ()
        return tuple(
            sorted(
                path.stem
                for path in self.plugin_directory.glob("*.py")
                if path.is_file() and self.is_valid_name(path.stem)
            )
        )

    @staticmethod
    def is_valid_name(name: str) -> bool:
        return isinstance(name, str) and _PLUGIN_NAME_PATTERN.fullmatch(name) is not None

    def load_module(self, name: str) -> ModuleType:
        if not self.is_valid_name(name):
            raise PluginNotFoundError(f"Invalid plugin name: {name!r}")

        plugin_path = self.plugin_directory / f"{name}.py"
        if not plugin_path.is_file():
            raise PluginNotFoundError(f"Plugin not found: {name}")
        return self.load_module_file(plugin_path)

    @staticmethod
    def load_module_file(plugin_path: Path) -> ModuleType:
        resolved_path = plugin_path.resolve()
        path_hash = hashlib.sha256(str(resolved_path).encode("utf-8")).hexdigest()
        source = plugin_path.read_bytes()
        content_hash = hashlib.sha256(source).hexdigest()
        cache_prefix = f"_fairybrowser_plugin_{path_hash}_"
        module_name = f"{cache_prefix}{content_hash}"
        cached_module = sys.modules.get(module_name)
        if isinstance(cached_module, ModuleType):
            return cached_module

        for cached_name in tuple(sys.modules):
            if cached_name.startswith(cache_prefix):
                sys.modules.pop(cached_name, None)

        spec = importlib.util.spec_from_file_location(module_name, plugin_path)
        if spec is None or spec.loader is None:
            raise PluginLoadError(f"Cannot load plugin module from {plugin_path}")

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            exec(compile(source, str(plugin_path), "exec"), module.__dict__)
        except Exception as error:
            sys.modules.pop(module_name, None)
            raise PluginLoadError(f"Failed to import plugin module from {plugin_path}") from error
        return module
