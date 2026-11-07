import os
import tempfile
from collections.abc import Mapping
from importlib.resources import files
from pathlib import Path

from fairybrowser.models import BrowserInfo
from fairybrowser.plugins.readers.exceptions import PageReaderPluginError, PageReaderPluginNotFoundError
from fairybrowser.plugins.readers.executor import PageReaderExecutor
from fairybrowser.plugins.readers.loader import PageReaderPluginLoader
from fairybrowser.plugins.readers.models import PageReaderProtocol
from fairybrowser.storage import StoragePathSolver


class PageReaderPluginRegistry:
    """Discover, load, and use named reader plugins."""

    def __init__(self, plugin_directory: Path | None = None) -> None:
        self.plugin_directory = (
            Path(plugin_directory).expanduser()
            if plugin_directory is not None
            else StoragePathSolver().reader_plugins_directory()
        )
        self._loader = PageReaderPluginLoader(self.plugin_directory)

    def list_plugins(self) -> tuple[str, ...]:
        """List installed plugin names without importing their code."""
        return self._loader.list_plugins()

    def fetch(self, name: str) -> str:
        """Return a plugin's Python source without importing or executing it."""
        if not self._loader.is_valid_name(name):
            raise PageReaderPluginNotFoundError(f"Invalid reader plugin name: {name!r}")
        plugin_path = self._loader.find_plugin_path(name)
        if plugin_path is None:
            raise PageReaderPluginNotFoundError(f"Reader plugin not found: {name}")
        return plugin_path.read_text(encoding="utf-8")

    def install_example(self) -> Path:
        """Install the bundled reader example, replacing any plugin named 'example'."""
        source = files("fairybrowser.plugins.readers").joinpath("example.py").read_text(encoding="utf-8")
        return self.install(source, overwrite=True)

    def load(self, name: str) -> PageReaderProtocol:
        """Load a trusted local plugin and create its reader."""
        return self._loader.load(name)

    def verify(self, name: str) -> PageReaderProtocol:
        """Load a trusted local plugin and validate its reader contract.

        This executes plugin module code, its class constructor, and its create method.
        It does not select or read a page.
        """
        return self.load(name)

    def can_read(self, name: str) -> bool:
        """Return whether a local plugin loads and satisfies the reader contract.

        This executes plugin module code, its class constructor, and its create method.
        A true result does not guarantee that a page can be selected or read.
        """
        try:
            self.verify(name)
        except PageReaderPluginError:
            return False
        return True

    def install(self, source: Path | str, *, overwrite: bool = False) -> Path:
        """Install a trusted plugin from a source Path or Python source string.

        Validation executes the plugin module, its class constructor, and its create method.
        String arguments are always treated as source code. Do not expose this developer utility
        as an installation flow for unknown users.
        """
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

    def read(
        self,
        name: str,
        browser_info: BrowserInfo | str | None = None,
        *,
        options: Mapping[str, object] | None = None,
    ) -> str | None:
        """Read the selected page using per-call reader context and options."""
        reader = self.load(name)
        return PageReaderExecutor(reader).read(browser_info, options=options)
