import os
import tempfile
from pathlib import Path
from typing import Any

from fairybrowser.invocation.models import InvocationConfiguration, InvocationExecutor, InvocationProtocol
from fairybrowser.invocation.plugin.exceptions import InvocationPluginError
from fairybrowser.invocation.plugin.loader import InvocationPluginLoader
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
        """Load a trusted local plugin, executing its module and factory code."""
        return self._loader.load(name)

    def verify(self, name: str) -> InvocationProtocol[Any, Any]:
        """Load a trusted local plugin and validate its Invocation contract.

        This executes plugin module code and its class constructor or factory.
        It does not run the invocation's browser operation.
        """
        return self.load(name)

    def can_execute(self, name: str) -> bool:
        """Return whether a local plugin loads and satisfies the Invocation contract.

        This executes plugin module code and its class constructor or factory.
        A true result does not guarantee that its browser operation will succeed.
        """
        try:
            self.verify(name)
        except InvocationPluginError:
            return False
        return True

    def install(self, source: Path | str, *, name: str | None = None, overwrite: bool = False) -> Path:
        """Install a trusted plugin for local development.

        Validation executes the plugin module and its class constructor or factory.
        Do not expose this developer utility as an installation flow for unknown users.
        """
        if isinstance(source, Path) or (isinstance(source, str) and source.endswith(".py")):
            source_path = Path(source).expanduser()
            if not source_path.is_file():
                raise FileNotFoundError(source_path)
            if name is not None:
                raise ValueError("name is derived from the plugin file name")
            plugin_name = source_path.stem
            source_bytes = source_path.read_bytes()
        elif isinstance(source, str):
            if name is None:
                raise ValueError("name is required when installing Python source text")
            plugin_name = name
            source_bytes = source.encode("utf-8")
        else:
            raise TypeError(f"Unsupported plugin source type: {type(source).__name__}")

        if not self._loader.is_valid_name(plugin_name):
            raise ValueError(f"Invalid invocation plugin name: {plugin_name!r}")

        self.plugin_directory.mkdir(parents=True, exist_ok=True)
        destination = self.plugin_directory / f"{plugin_name}.py"
        if destination.exists() and not overwrite:
            raise FileExistsError(destination)

        with tempfile.TemporaryDirectory(prefix=".install-", dir=self.plugin_directory) as temporary_directory:
            staged_source = Path(temporary_directory) / f"{plugin_name}.py"
            staged_source.write_bytes(source_bytes)
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
        output_folder: Path | None = None,
    ) -> Any:
        """Execute an installed trusted plugin in the current process."""
        invocation = self.load(name)
        return InvocationExecutor.from_any(invocation).invoke(
            input=input,
            configuration=configuration,
            output_folder=output_folder,
        )
