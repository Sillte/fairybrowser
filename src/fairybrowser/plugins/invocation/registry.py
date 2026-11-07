import os
import tempfile
from collections.abc import Mapping
from importlib.resources import files
from pathlib import Path
from typing import Any

from fairybrowser.invocation.models import InvocationConfiguration, InvocationExecutor, InvocationProtocol
from fairybrowser.plugins.invocation.exceptions import (
    InvalidInvocationPluginError,
    InvocationPluginError,
    InvocationPluginNotFoundError,
)
from fairybrowser.plugins.invocation.loader import InvocationPluginLoader
from fairybrowser.storage import StoragePathSolver


class InvocationPluginRegistry:
    """Discover, load, and execute named invocation plugins."""

    def __init__(self, plugin_directory: Path | None = None) -> None:
        self.plugin_directory = (
            Path(plugin_directory).expanduser()
            if plugin_directory is not None
            else StoragePathSolver().invocation_plugins_directory()
        )
        self._loader = InvocationPluginLoader(self.plugin_directory)

    def list_plugins(self) -> tuple[str, ...]:
        """List installed plugin names without importing their code."""
        return self._loader.list_plugins()

    def fetch(self, name: str) -> str:
        """Return a plugin's Python source without importing or executing it."""
        if not self._loader.is_valid_name(name):
            raise InvocationPluginNotFoundError(f"Invalid invocation plugin name: {name!r}")
        plugin_path = self._loader.find_plugin_path(name)
        if plugin_path is None:
            raise InvocationPluginNotFoundError(f"Invocation plugin not found: {name}")
        return plugin_path.read_text(encoding="utf-8")

    def install_example(self) -> Path:
        """Install the bundled invocation example, replacing any plugin named 'example'."""
        source = files("fairybrowser.plugins.invocation").joinpath("example.py").read_text(encoding="utf-8")
        return self.install(source, overwrite=True)

    def load(self, name: str) -> InvocationProtocol[Any, Any]:
        """Load a trusted local plugin and create its Invocation."""
        return self._loader.load(name)

    def verify(self, name: str) -> InvocationProtocol[Any, Any]:
        """Load a trusted local plugin and validate its Invocation contract.

        This executes plugin module code, its class constructor, and its create method.
        It does not run the invocation's browser operation.
        """
        return self.load(name)

    def can_execute(self, name: str) -> bool:
        """Return whether a local plugin loads and satisfies the Invocation contract.

        This executes plugin module code, its class constructor, and its create method.
        A true result does not guarantee that its browser operation will succeed.
        """
        try:
            self.verify(name)
        except InvocationPluginError:
            return False
        return True

    def install(
        self,
        source: Path | str,
        *,
        overwrite: bool = False,
        filename: str | None = None,
    ) -> Path:
        """Install a trusted source file containing one or more invocation plugins.

        Validation executes the plugin module, its plugin class constructors, and their create methods.
        String arguments are always treated as source code. A filename is required for a source string
        containing multiple invocation plugins. Do not expose this developer utility as an installation
        flow for unknown users.
        """
        source_path: Path | None = None
        if isinstance(source, Path):
            source_path = Path(source).expanduser()
            if not source_path.is_file():
                raise FileNotFoundError(source_path)
            source_bytes = source_path.read_bytes()
        elif isinstance(source, str):
            source_bytes = source.encode("utf-8")
        else:
            raise TypeError(f"Unsupported plugin source type: {type(source).__name__}")

        self.plugin_directory.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".install-", dir=self.plugin_directory) as temporary_directory:
            staged_source = Path(temporary_directory) / "plugin.py"
            staged_source.write_bytes(source_bytes)
            plugin_names = self._loader.get_plugin_names(staged_source)
            for plugin_name in plugin_names:
                self._loader._load_plugin_file(staged_source, plugin_name)

            existing_paths = {
                path for name in plugin_names if (path := self._loader.find_plugin_path(name)) is not None
            }
            if len(existing_paths) > 1:
                raise InvalidInvocationPluginError("Cannot overwrite plugins stored in different source files together")
            existing_path = next(iter(existing_paths), None)
            if filename is None:
                if existing_path is not None:
                    filename = existing_path.name
                elif len(plugin_names) == 1:
                    filename = f"{plugin_names[0]}.py"
                elif source_path is not None:
                    filename = source_path.name
                else:
                    raise ValueError("filename is required when installing multiple invocation plugins from source text")
            self._validate_install_filename(filename)
            destination = self.plugin_directory / filename
            if existing_path is not None and not overwrite:
                raise FileExistsError(existing_path)
            if existing_path is not None and destination != existing_path:
                raise InvalidInvocationPluginError(
                    f"Use the existing bundle filename {existing_path.name!r} when overwriting these plugins"
                )
            if destination.exists() and not overwrite:
                raise FileExistsError(destination)

            if overwrite:
                os.replace(staged_source, destination)
            else:
                os.link(staged_source, destination)

        return destination

    @staticmethod
    def _validate_install_filename(filename: str) -> None:
        path = Path(filename)
        if (
            path.name != filename
            or path.suffix != ".py"
            or not InvocationPluginLoader.is_valid_name(path.stem)
        ):
            raise ValueError("filename must be a valid .py filename without a directory component")

    def invoke(
        self,
        name: str,
        input: Any,
        configuration: InvocationConfiguration | None = None,
        *,
        options: Mapping[str, object] | None = None,
        output_folder: Path | None = None,
    ) -> Any:
        """Execute an installed trusted plugin in the current process."""
        invocation = self.load(name)
        return InvocationExecutor.from_any(invocation).invoke(
            input=input,
            configuration=configuration,
            options=options,
            output_folder=output_folder,
        )
