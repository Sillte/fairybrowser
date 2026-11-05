import os
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from fairybrowser.invocation.models import InvocationConfiguration, InvocationExecutor, InvocationProtocol
from fairybrowser.plugins.invocation.exceptions import InvocationPluginError
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

    def install(self, source: Path | str, *, overwrite: bool = False) -> Path:
        """Install a trusted plugin whose class declares its own name.

        Validation executes the plugin module, its class constructor, and its create method.
        Do not expose this developer utility as an installation flow for unknown users.
        """
        if isinstance(source, Path) or (isinstance(source, str) and source.endswith(".py")):
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
            plugin_name = self._loader.get_plugin_name(staged_source)
            existing_path = self._loader.find_plugin_path(plugin_name)
            destination = existing_path if existing_path is not None else self.plugin_directory / f"{plugin_name}.py"
            if destination.exists() and not overwrite:
                raise FileExistsError(destination)

            self._loader._load_plugin_file(staged_source, plugin_name)
            if overwrite:
                os.replace(staged_source, destination)
            else:
                os.link(staged_source, destination)

        return destination

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
