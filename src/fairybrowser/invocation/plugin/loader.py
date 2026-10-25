import hashlib
import importlib.util
import inspect
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, cast

from fairybrowser.invocation.models import InvocationProtocol
from fairybrowser.invocation.plugin.exceptions import (
    InvalidInvocationPluginError,
    InvocationPluginLoadError,
    InvocationPluginNotFoundError,
)
from fairybrowser.invocation.plugin.models import InvocationPlugin

_PLUGIN_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


class InvocationPluginLoader:
    """Discover and load Python invocation plugins from a directory."""

    def __init__(self, plugin_directory: Path) -> None:
        self.plugin_directory = Path(plugin_directory).expanduser()

    def list_plugins(self) -> tuple[str, ...]:
        if not self.plugin_directory.is_dir():
            return ()
        return tuple(
            sorted(
                path.stem
                for path in self.plugin_directory.glob("*.py")
                if path.is_file() and _PLUGIN_NAME_PATTERN.fullmatch(path.stem)
            )
        )

    @staticmethod
    def is_valid_name(name: str) -> bool:
        return isinstance(name, str) and _PLUGIN_NAME_PATTERN.fullmatch(name) is not None

    def load(self, name: str) -> InvocationProtocol[Any, Any]:
        if not self.is_valid_name(name):
            raise InvocationPluginNotFoundError(f"Invalid invocation plugin name: {name!r}")

        plugin_path = self.plugin_directory / f"{name}.py"
        if not plugin_path.is_file():
            raise InvocationPluginNotFoundError(f"Invocation plugin not found: {name}")
        return self._load_plugin_file(plugin_path, name)

    def _load_plugin_file(self, plugin_path: Path, name: str) -> InvocationProtocol[Any, Any]:
        module = self._load_module(plugin_path)
        candidate = self._find_plugin_candidate(module, name)

        try:
            if inspect.isclass(candidate):
                plugin_type = cast(type[InvocationPlugin[Any, Any]], candidate)
                invocation = plugin_type().create_invocation()
            else:
                factory = cast(Callable[[], object], candidate)
                invocation = factory()
        except Exception as error:
            raise InvocationPluginLoadError(f"Failed to create invocation from plugin {name!r}") from error

        if not self._implements_invocation_contract(invocation):
            raise InvalidInvocationPluginError(
                f"Plugin candidate in {name!r} must return an InvocationProtocol implementation"
            )
        return cast(InvocationProtocol[Any, Any], invocation)

    @staticmethod
    def _find_plugin_candidate(module: ModuleType, name: str) -> object:
        candidates: list[object] = []
        for candidate in vars(module).values():
            if getattr(candidate, "__module__", None) != module.__name__:
                continue

            is_plugin_class = (
                inspect.isclass(candidate)
                and issubclass(candidate, InvocationPlugin)
                and not inspect.isabstract(candidate)
            )
            is_plugin_factory = inspect.isfunction(candidate) and getattr(
                candidate, "__fairybrowser_invocation_plugin__", False
            )
            if (is_plugin_class or is_plugin_factory) and candidate not in candidates:
                candidates.append(candidate)

        if len(candidates) != 1:
            raise InvalidInvocationPluginError(
                f"Plugin module {name!r} must define exactly one top-level plugin candidate; found {len(candidates)}"
            )
        return candidates[0]

    def _load_module(self, plugin_path: Path) -> ModuleType:
        resolved_path = plugin_path.resolve()
        path_hash = hashlib.sha256(str(resolved_path).encode("utf-8")).hexdigest()
        source = plugin_path.read_bytes()
        content_hash = hashlib.sha256(source).hexdigest()
        cache_prefix = f"_fairybrowser_invocation_plugin_{path_hash}_"
        module_name = f"{cache_prefix}{content_hash}"
        cached_module = sys.modules.get(module_name)
        if isinstance(cached_module, ModuleType):
            return cached_module

        for cached_name in tuple(sys.modules):
            if cached_name.startswith(cache_prefix):
                sys.modules.pop(cached_name, None)

        spec = importlib.util.spec_from_file_location(module_name, plugin_path)
        if spec is None or spec.loader is None:
            raise InvocationPluginLoadError(f"Cannot load invocation plugin from {plugin_path}")

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            exec(compile(source, str(plugin_path), "exec"), module.__dict__)
        except Exception as error:
            sys.modules.pop(module_name, None)
            raise InvocationPluginLoadError(f"Failed to import invocation plugin from {plugin_path}") from error
        return module

    @staticmethod
    def _implements_invocation_contract(invocation: object) -> bool:
        """Check protocol members and ensure required methods are callable."""
        return (
            isinstance(invocation, InvocationProtocol)
            and callable(getattr(invocation, "start", None))
            and callable(getattr(invocation, "on_completed", None))
        )
