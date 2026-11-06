from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from playwright.sync_api import Page

from fairybrowser.models import BrowserInfo
from fairybrowser.plugins.reader import (
    DuplicateReaderPluginNameError,
    InvalidReaderPluginError,
    ReaderPluginLoader,
    ReaderPluginLoadError,
    ReaderPluginNotFoundError,
    ReaderPluginRegistry,
)
from fairybrowser.storage import StoragePathSolver


def _valid_plugin_source(name: str = "sample") -> str:
    return f'''
class SamplePlugin:
    name = {name!r}

    def create(self):
        return SampleReader()


class SampleReader:
    def select(self, pages):
        return pages[0] if pages else None

    def read(self, page):
        return "read"
'''


def test_reader_plugin_loader_lists_names_without_importing_plugin_code(tmp_path: Path):
    marker = tmp_path / "imported.txt"
    (tmp_path / "reader.py").write_text(
        f'''
from pathlib import Path
Path({str(marker)!r}).write_text("imported")

class ReaderPlugin:
    name = "sample"
    def create(self):
        raise RuntimeError("not called during listing")
''',
        encoding="utf-8",
    )
    loader = ReaderPluginLoader(tmp_path)

    assert loader.list_plugins() == ("sample",)
    assert not marker.exists()


def test_reader_plugin_loader_loads_named_reader(tmp_path: Path):
    (tmp_path / "different-filename.py").write_text(_valid_plugin_source("stable-id"), encoding="utf-8")
    loader = ReaderPluginLoader(tmp_path)

    reader = loader.load("stable-id")
    first_page = cast(Page, object())

    assert reader.select([first_page]) is first_page
    assert reader.select([]) is None
    assert reader.read(first_page) == "read"


def test_reader_plugin_loader_rejects_missing_and_invalid_plugins(tmp_path: Path):
    (tmp_path / "invalid.py").write_text(
        '''
class Plugin:
    name = "invalid"
    def create_reader(self): return object()
''',
        encoding="utf-8",
    )
    loader = ReaderPluginLoader(tmp_path)

    with pytest.raises(ReaderPluginNotFoundError):
        loader.load("../invalid")
    with pytest.raises(ReaderPluginNotFoundError):
        loader.load("missing")
    with pytest.raises(InvalidReaderPluginError, match="callable create"):
        loader.load("invalid")


def test_reader_plugin_loader_rejects_invalid_reader_result(tmp_path: Path):
    (tmp_path / "invalid-result.py").write_text(
        '''
class Plugin:
    name = "bad-result"
    def create(self): return object()
''',
        encoding="utf-8",
    )
    loader = ReaderPluginLoader(tmp_path)

    with pytest.raises(InvalidReaderPluginError, match="ReaderProtocol"):
        loader.load("bad-result")


def test_reader_plugin_loader_rejects_duplicate_names(tmp_path: Path):
    for filename in ("first.py", "second.py"):
        (tmp_path / filename).write_text(_valid_plugin_source("duplicate"), encoding="utf-8")
    loader = ReaderPluginLoader(tmp_path)

    with pytest.raises(DuplicateReaderPluginNameError, match="duplicate"):
        loader.list_plugins()


def test_reader_plugin_loader_wraps_plugin_creation_errors(tmp_path: Path):
    (tmp_path / "broken.py").write_text(
        '''
class Plugin:
    name = "broken"
    def create(self): raise RuntimeError("failure")
''',
        encoding="utf-8",
    )
    loader = ReaderPluginLoader(tmp_path)

    with pytest.raises(ReaderPluginLoadError, match="Failed to create reader"):
        loader.load("broken")


def test_reader_plugin_registry_installs_and_checks_plugins(tmp_path: Path):
    registry = ReaderPluginRegistry(tmp_path / "registry")

    installed = registry.install(_valid_plugin_source())

    assert installed == tmp_path / "registry" / "sample.py"
    assert registry.list_plugins() == ("sample",)
    assert registry.can_read("sample")
    with pytest.raises(FileExistsError):
        registry.install(_valid_plugin_source())


def test_reader_plugin_registry_makes_example(tmp_path: Path):
    plugin_directory = tmp_path / "registry"
    plugin_directory.mkdir()
    (plugin_directory / "example.py").write_text("old content", encoding="utf-8")
    registry = ReaderPluginRegistry(plugin_directory)

    example_path = registry.make_example()
    reader = registry.load("example")

    class FakePage:
        def title(self) -> str:
            return "Example page"

    page = cast(Page, FakePage())
    assert example_path == plugin_directory / "example.py"
    assert reader.select([page]) is page
    assert reader.read(page) == "Example page"


def test_reader_plugin_registry_reads_selected_page(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = '''
class SamplePlugin:
    name = "sample"

    def create(self):
        return SampleReader()


class SampleReader:
    def select(self, pages):
        return pages[-1] if pages else None

    def read(self, page):
        return page.label
'''
    (tmp_path / "reader.py").write_text(source, encoding="utf-8")
    registry = ReaderPluginRegistry(tmp_path)
    browser_info = BrowserInfo(name="test")

    class FakePage:
        def __init__(self, label: str, closed: bool = False):
            self.label = label
            self.closed = closed

        def is_closed(self) -> bool:
            return self.closed

    page_in_first_context = FakePage("first")
    closed_page = FakePage("closed", closed=True)
    page_in_second_context = FakePage("second")
    browser = SimpleNamespace(
        contexts=[
            SimpleNamespace(pages=[page_in_first_context, closed_page]),
            SimpleNamespace(pages=[page_in_second_context]),
        ]
    )

    @contextmanager
    def fake_sync_browser(*, info: BrowserInfo) -> Iterator[SimpleNamespace]:
        assert info == browser_info
        yield browser

    monkeypatch.setattr("fairybrowser.plugins.reader.registry.sync_browser", fake_sync_browser)

    assert registry.read("sample", browser_info) == "second"

    browser.contexts = [SimpleNamespace(pages=[])]
    assert registry.read("sample", browser_info) is None


def test_plugin_directories_are_nested_under_application_data_plugins(tmp_path: Path):
    data_home = tmp_path / "data"
    solver = StoragePathSolver(home_directory=tmp_path, data_home=data_home)
    plugins_directory = data_home / "fairybrowser" / "plugins"

    assert solver.invocation_plugins_directory() == plugins_directory / "invocations"
    assert solver.reader_plugins_directory() == plugins_directory / "readers"
