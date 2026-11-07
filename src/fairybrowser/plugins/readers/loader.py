import ast
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from fairybrowser.plugin import PluginLoadError, PluginModuleLoader
from fairybrowser.plugins.readers.exceptions import (
    DuplicatePageReaderPluginNameError,
    InvalidPageReaderPluginError,
    PageReaderPluginLoadError,
    PageReaderPluginNotFoundError,
)
from fairybrowser.plugins.readers.models import PageReaderPluginProtocol, PageReaderProtocol


@dataclass(frozen=True)
class _PluginMetadata:
    name: str
    class_name: str
    path: Path


class PageReaderPluginLoader:
    """Discover named reader plugins and load their trusted Python code."""

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
        metadata = self._plugin_metadata_for_file(plugin_path)
        if metadata is None:
            raise InvalidPageReaderPluginError(f"No named reader plugin found in {plugin_path}")
        return metadata.name

    def find_plugin_path(self, name: str) -> Path | None:
        metadata = self._plugin_metadata_by_name().get(name)
        return metadata.path if metadata is not None else None

    def _load_plugin_file(self, plugin_path: Path, name: str) -> PageReaderProtocol:
        metadata = self._plugin_metadata_for_file(plugin_path)
        if metadata is None or metadata.name != name:
            raise InvalidPageReaderPluginError(f"Plugin file {plugin_path} must declare the requested name {name!r}")
        try:
            module = self._module_loader.load_module_file(plugin_path)
        except PluginLoadError as error:
            raise PageReaderPluginLoadError(str(error)) from error

        candidate = vars(module).get(metadata.class_name)
        if not isinstance(candidate, type) or getattr(candidate, "__module__", None) != module.__name__:
            raise InvalidPageReaderPluginError(f"Plugin class {metadata.class_name!r} was not found in {plugin_path}")
        try:
            plugin = candidate()
        except Exception as error:
            raise PageReaderPluginLoadError(f"Failed to create reader plugin {name!r}") from error

        if not self._implements_plugin_contract(plugin, name):
            raise InvalidPageReaderPluginError(
                f"Plugin {name!r} must define the requested name and a callable create method"
            )
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
            metadata = self._plugin_metadata_for_file(plugin_path)
            if metadata is None:
                continue
            previous = metadata_by_name.get(metadata.name)
            if previous is not None:
                raise DuplicatePageReaderPluginNameError(
                    f"Reader plugin name {metadata.name!r} is declared in both {previous.path} and {plugin_path}"
                )
            metadata_by_name[metadata.name] = metadata
        return metadata_by_name

    def _plugin_metadata_for_file(self, plugin_path: Path) -> _PluginMetadata | None:
        try:
            source = plugin_path.read_text(encoding="utf-8")
        except OSError as error:
            raise PageReaderPluginLoadError(f"Cannot read reader plugin source {plugin_path}") from error
        try:
            module = ast.parse(source, filename=str(plugin_path))
        except SyntaxError as error:
            raise PageReaderPluginLoadError(f"Invalid Python syntax in reader plugin {plugin_path}") from error

        candidates: list[_PluginMetadata] = []
        for node in module.body:
            if not isinstance(node, ast.ClassDef):
                continue
            declared_name = self._class_name(node, plugin_path)
            if declared_name is None:
                continue
            if not self.is_valid_name(declared_name):
                raise InvalidPageReaderPluginError(f"Invalid reader plugin name {declared_name!r} in {plugin_path}")
            candidates.append(_PluginMetadata(declared_name, node.name, plugin_path))

        if len(candidates) > 1:
            raise InvalidPageReaderPluginError(
                f"Plugin module {plugin_path} must declare exactly one named plugin; found {len(candidates)}"
            )
        return candidates[0] if candidates else None

    @staticmethod
    def _class_name(node: ast.ClassDef, plugin_path: Path) -> str | None:
        assignments: list[ast.expr | None] = []
        for statement in node.body:
            if isinstance(statement, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == "name" for target in statement.targets
            ):
                assignments.append(statement.value)
            elif isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
                if statement.target.id == "name":
                    assignments.append(statement.value)

        if not assignments:
            return None
        if len(assignments) != 1 or not isinstance(assignments[0], ast.Constant) or not isinstance(
            assignments[0].value, str
        ):
            raise InvalidPageReaderPluginError(
                f"Plugin class {node.name!r} in {plugin_path} must declare a literal string name"
            )
        return assignments[0].value

    @staticmethod
    def _implements_plugin_contract(plugin: object, expected_name: str) -> bool:
        return (
            getattr(plugin, "name", None) == expected_name
            and callable(getattr(plugin, "create", None))
            and isinstance(plugin, PageReaderPluginProtocol)
        )

    @staticmethod
    def _implements_reader_contract(reader: object) -> bool:
        return (
            isinstance(reader, PageReaderProtocol)
            and callable(getattr(reader, "select", None))
            and callable(getattr(reader, "read", None))
        )
