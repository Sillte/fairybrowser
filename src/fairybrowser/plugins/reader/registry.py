import os
import tempfile
from pathlib import Path

from fairybrowser.models import BrowserInfo
from fairybrowser.plugins.reader.exceptions import ReaderPluginError
from fairybrowser.plugins.reader.loader import ReaderPluginLoader
from fairybrowser.plugins.reader.models import ReaderProtocol
from fairybrowser.runners import sync_browser
from fairybrowser.storage import StoragePathSolver


class ReaderPluginRegistry:
    """Discover, load, and use named reader plugins."""

    def __init__(self, plugin_directory: Path | None = None) -> None:
        self.plugin_directory = (
            Path(plugin_directory).expanduser()
            if plugin_directory is not None
            else StoragePathSolver().reader_plugins_directory()
        )
        self._loader = ReaderPluginLoader(self.plugin_directory)

    def list_plugins(self) -> tuple[str, ...]:
        """List installed plugin names without importing their code."""
        return self._loader.list_plugins()

    def make_example(self) -> Path:
        """Write a simple reader plugin example to the plugin directory."""
        self.plugin_directory.mkdir(parents=True, exist_ok=True)
        example_path = self.plugin_directory / "example.py"
        example_path.write_text(
            '''class ExampleReaderPlugin:
    name = "example"

    def create(self):
        return ExampleReader()


class ExampleReader:
    def select(self, pages):
        return pages[0] if pages else None

    def read(self, page):
        return page.title()
''',
            encoding="utf-8",
        )
        return example_path

    def load(self, name: str) -> ReaderProtocol:
        """Load a trusted local plugin and create its reader."""
        return self._loader.load(name)

    def verify(self, name: str) -> ReaderProtocol:
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
        except ReaderPluginError:
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

    def read(self, name: str, browser_info: BrowserInfo | str | None = None) -> str | None:
        """Read the selected page in the managed browser, or return None if none is suitable."""
        reader = self.load(name)
        with sync_browser(info=browser_info) as browser:
            pages = tuple(
                page for browser_context in browser.contexts for page in browser_context.pages if not page.is_closed()
            )
            page = reader.select(pages)
            if page is None:
                return None
            if page.is_closed() or not any(
                page is candidate
                for browser_context in browser.contexts
                for candidate in browser_context.pages
                if not candidate.is_closed()
            ):
                raise RuntimeError("The reader must select an open page from the managed browser.")
            return reader.read(page)
