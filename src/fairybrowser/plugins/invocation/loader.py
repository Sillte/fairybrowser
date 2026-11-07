from dataclasses import dataclass
from inspect import isabstract
from pathlib import Path
from typing import Any, cast

from fairybrowser.invocation.models import InvocationProtocol
from fairybrowser.plugin import PluginLoadError, PluginModuleLoader
from fairybrowser.plugins._discovery import PluginDiscoveryError, discover_plugin_classes
from fairybrowser.plugins.invocation.exceptions import (
    DuplicateInvocationPluginNameError,
    InvalidInvocationPluginError,
    InvocationPluginLoadError,
    InvocationPluginNotFoundError,
)
from fairybrowser.plugins.invocation.models import InvocationPlugin


@dataclass(frozen=True)
class _PluginMetadata:
    name: str
    class_name: str
    path: Path


class InvocationPluginLoader:
    """Discover ABC-based invocation plugins and load their trusted Python code."""

    _BASE_NAME = "InvocationPlugin"
    _ALLOWED_IMPORT_MODULES = frozenset(
        {
            "fairybrowser.plugins",
            "fairybrowser.plugins.invocation",
            "fairybrowser.plugins.invocation.models",
        }
    )

    def __init__(self, plugin_directory: Path) -> None:
        self._module_loader = PluginModuleLoader(plugin_directory)
        self.plugin_directory = self._module_loader.plugin_directory

    def list_plugins(self) -> tuple[str, ...]:
        return tuple(sorted(self._plugin_metadata_by_name()))

    @staticmethod
    def is_valid_name(name: str) -> bool:
        return PluginModuleLoader.is_valid_name(name)

    def load(self, name: str) -> InvocationProtocol[Any, Any]:
        if not self.is_valid_name(name):
            raise InvocationPluginNotFoundError(f"Invalid invocation plugin name: {name!r}")
        metadata = self._plugin_metadata_by_name().get(name)
        if metadata is None:
            raise InvocationPluginNotFoundError(f"Invocation plugin not found: {name}")
        return self._load_plugin_file(metadata.path, name)

    def get_plugin_name(self, plugin_path: Path) -> str:
        names = self.get_plugin_names(plugin_path)
        if len(names) != 1:
            raise InvalidInvocationPluginError(
                f"Expected one invocation plugin in {plugin_path}; found {len(names)}"
            )
        return names[0]

    def get_plugin_names(self, plugin_path: Path) -> tuple[str, ...]:
        names = tuple(metadata.name for metadata in self._plugin_metadata_for_file(plugin_path))
        if not names:
            raise InvalidInvocationPluginError(f"No named invocation plugin found in {plugin_path}")
        return names

    def find_plugin_path(self, name: str) -> Path | None:
        metadata = self._plugin_metadata_by_name().get(name)
        return metadata.path if metadata is not None else None

    def _load_plugin_file(self, plugin_path: Path, name: str) -> InvocationProtocol[Any, Any]:
        metadata = next(
            (item for item in self._plugin_metadata_for_file(plugin_path) if item.name == name),
            None,
        )
        if metadata is None:
            raise InvalidInvocationPluginError(
                f"Plugin file {plugin_path} must declare the requested name {name!r}"
            )
        try:
            module = self._module_loader.load_module_file(plugin_path)
        except PluginLoadError as error:
            raise InvocationPluginLoadError(str(error)) from error

        candidate = vars(module).get(metadata.class_name)
        if (
            not isinstance(candidate, type)
            or getattr(candidate, "__module__", None) != module.__name__
            or InvocationPlugin not in candidate.__bases__
            or isabstract(candidate)
            or getattr(candidate, "name", None) != name
            or not callable(getattr(candidate, "create", None))
        ):
            raise InvalidInvocationPluginError(
                f"Plugin class {metadata.class_name!r} in {plugin_path} must directly inherit from "
                f"{self._BASE_NAME} and implement its abstract methods"
            )
        try:
            plugin = candidate()
        except Exception as error:
            raise InvocationPluginLoadError(f"Failed to create plugin {name!r}") from error

        try:
            invocation = plugin.create()
        except Exception as error:
            raise InvocationPluginLoadError(f"Failed to create invocation from plugin {name!r}") from error

        if not self._implements_invocation_contract(invocation):
            raise InvalidInvocationPluginError(
                f"Plugin {name!r} must return an InvocationProtocol implementation"
            )
        return cast(InvocationProtocol[Any, Any], invocation)

    def _plugin_metadata_by_name(self) -> dict[str, _PluginMetadata]:
        metadata_by_name: dict[str, _PluginMetadata] = {}
        if not self.plugin_directory.is_dir():
            return metadata_by_name
        for plugin_path in sorted(self.plugin_directory.glob("*.py")):
            for metadata in self._plugin_metadata_for_file(plugin_path):
                previous = metadata_by_name.get(metadata.name)
                if previous is not None:
                    raise DuplicateInvocationPluginNameError(
                        f"Invocation plugin name {metadata.name!r} is declared in both "
                        f"{previous.path} and {plugin_path}"
                    )
                metadata_by_name[metadata.name] = metadata
        return metadata_by_name

    def _plugin_metadata_for_file(self, plugin_path: Path) -> tuple[_PluginMetadata, ...]:
        try:
            source = plugin_path.read_text(encoding="utf-8")
        except OSError as error:
            raise InvocationPluginLoadError(f"Cannot read invocation plugin source {plugin_path}") from error
        try:
            discovered = discover_plugin_classes(
                source,
                filename=str(plugin_path),
                base_name=self._BASE_NAME,
                allowed_import_modules=self._ALLOWED_IMPORT_MODULES,
            )
        except SyntaxError as error:
            raise InvocationPluginLoadError(f"Invalid Python syntax in invocation plugin {plugin_path}") from error
        except PluginDiscoveryError as error:
            raise InvalidInvocationPluginError(str(error)) from error

        candidates: list[_PluginMetadata] = []
        for item in discovered:
            if not self.is_valid_name(item.name):
                raise InvalidInvocationPluginError(f"Invalid invocation plugin name {item.name!r} in {plugin_path}")
            candidates.append(_PluginMetadata(item.name, item.class_name, plugin_path))

        names = [metadata.name for metadata in candidates]
        if len(names) != len(set(names)):
            duplicate = next(name for index, name in enumerate(names) if name in names[:index])
            raise DuplicateInvocationPluginNameError(
                f"Invocation plugin name {duplicate!r} is declared more than once in {plugin_path}"
            )
        return tuple(candidates)

    @staticmethod
    def _implements_invocation_contract(invocation: object) -> bool:
        """Check protocol members and ensure required methods are callable."""
        return (
            isinstance(invocation, InvocationProtocol)
            and callable(getattr(invocation, "select", None))
            and callable(getattr(invocation, "start", None))
            and callable(getattr(invocation, "on_completed", None))
        )
