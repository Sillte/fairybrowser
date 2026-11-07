from dataclasses import dataclass
from inspect import isabstract
from pathlib import Path
from typing import cast

from fairybrowser.plugin import PluginLoadError, PluginModuleLoader
from fairybrowser.plugins._discovery import PluginDiscoveryError, discover_plugin_classes
from fairybrowser.plugins.readers.exceptions import (
    DuplicatePageReaderPluginNameError,
    InvalidPageReaderPluginError,
    PageReaderPluginLoadError,
    PageReaderPluginNotFoundError,
)
from fairybrowser.plugins.readers.models import PageReaderPlugin, PageReaderProtocol


@dataclass(frozen=True)
class _PluginMetadata:
    name: str
    class_name: str
    path: Path


class PageReaderPluginLoader:
    """Discover ABC-based reader plugins and load their trusted Python code."""

    _BASE_NAME = "PageReaderPlugin"
    _ALLOWED_IMPORT_MODULES = frozenset(
        {
            "fairybrowser.plugins",
            "fairybrowser.plugins.readers",
            "fairybrowser.plugins.readers.models",
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

    def load(self, name: str) -> PageReaderProtocol:
        if not self.is_valid_name(name):
            raise PageReaderPluginNotFoundError(f"Invalid reader plugin name: {name!r}")
        metadata = self._plugin_metadata_by_name().get(name)
        if metadata is None:
            raise PageReaderPluginNotFoundError(f"Reader plugin not found: {name}")
        return self._load_plugin_file(metadata.path, name)

    def get_plugin_name(self, plugin_path: Path) -> str:
        names = self.get_plugin_names(plugin_path)
        if len(names) != 1:
            raise InvalidPageReaderPluginError(f"Expected one reader plugin in {plugin_path}; found {len(names)}")
        return names[0]

    def get_plugin_names(self, plugin_path: Path) -> tuple[str, ...]:
        names = tuple(metadata.name for metadata in self._plugin_metadata_for_file(plugin_path))
        if not names:
            raise InvalidPageReaderPluginError(f"No named reader plugin found in {plugin_path}")
        return names

    def find_plugin_path(self, name: str) -> Path | None:
        metadata = self._plugin_metadata_by_name().get(name)
        return metadata.path if metadata is not None else None

    def _load_plugin_file(self, plugin_path: Path, name: str) -> PageReaderProtocol:
        metadata = next(
            (item for item in self._plugin_metadata_for_file(plugin_path) if item.name == name),
            None,
        )
        if metadata is None:
            raise InvalidPageReaderPluginError(f"Plugin file {plugin_path} must declare the requested name {name!r}")
        try:
            module = self._module_loader.load_module_file(plugin_path)
        except PluginLoadError as error:
            raise PageReaderPluginLoadError(str(error)) from error

        candidate = vars(module).get(metadata.class_name)
        if (
            not isinstance(candidate, type)
            or getattr(candidate, "__module__", None) != module.__name__
            or PageReaderPlugin not in candidate.__bases__
            or isabstract(candidate)
            or getattr(candidate, "name", None) != name
            or not callable(getattr(candidate, "create", None))
        ):
            raise InvalidPageReaderPluginError(
                f"Plugin class {metadata.class_name!r} in {plugin_path} must directly inherit from "
                f"{self._BASE_NAME} and implement its abstract methods"
            )
        try:
            plugin = candidate()
        except Exception as error:
            raise PageReaderPluginLoadError(f"Failed to create reader plugin {name!r}") from error

        try:
            reader = plugin.create()
        except Exception as error:
            raise PageReaderPluginLoadError(f"Failed to create reader from plugin {name!r}") from error

        if not self._implements_reader_contract(reader):
            raise InvalidPageReaderPluginError(f"Plugin {name!r} must return a PageReaderProtocol implementation")
        return cast(PageReaderProtocol, reader)

    def _plugin_metadata_by_name(self) -> dict[str, _PluginMetadata]:
        metadata_by_name: dict[str, _PluginMetadata] = {}
        if not self.plugin_directory.is_dir():
            return metadata_by_name
        for plugin_path in sorted(self.plugin_directory.glob("*.py")):
            for metadata in self._plugin_metadata_for_file(plugin_path):
                previous = metadata_by_name.get(metadata.name)
                if previous is not None:
                    raise DuplicatePageReaderPluginNameError(
                        f"Reader plugin name {metadata.name!r} is declared in both {previous.path} and {plugin_path}"
                    )
                metadata_by_name[metadata.name] = metadata
        return metadata_by_name

    def _plugin_metadata_for_file(self, plugin_path: Path) -> tuple[_PluginMetadata, ...]:
        try:
            source = plugin_path.read_text(encoding="utf-8")
        except OSError as error:
            raise PageReaderPluginLoadError(f"Cannot read reader plugin source {plugin_path}") from error
        try:
            discovered = discover_plugin_classes(
                source,
                filename=str(plugin_path),
                base_name=self._BASE_NAME,
                allowed_import_modules=self._ALLOWED_IMPORT_MODULES,
            )
        except SyntaxError as error:
            raise PageReaderPluginLoadError(f"Invalid Python syntax in reader plugin {plugin_path}") from error
        except PluginDiscoveryError as error:
            raise InvalidPageReaderPluginError(str(error)) from error

        candidates: list[_PluginMetadata] = []
        for item in discovered:
            if not self.is_valid_name(item.name):
                raise InvalidPageReaderPluginError(f"Invalid reader plugin name {item.name!r} in {plugin_path}")
            candidates.append(_PluginMetadata(item.name, item.class_name, plugin_path))

        names = [metadata.name for metadata in candidates]
        if len(names) != len(set(names)):
            duplicate = next(name for index, name in enumerate(names) if name in names[:index])
            raise DuplicatePageReaderPluginNameError(
                f"Reader plugin name {duplicate!r} is declared more than once in {plugin_path}"
            )
        return tuple(candidates)

    @staticmethod
    def _implements_reader_contract(reader: object) -> bool:
        return (
            isinstance(reader, PageReaderProtocol)
            and callable(getattr(reader, "select", None))
            and callable(getattr(reader, "read", None))
        )
