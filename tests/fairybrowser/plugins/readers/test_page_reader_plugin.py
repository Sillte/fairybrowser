from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from playwright.sync_api import Page

from fairybrowser.models import BrowserInfo
from fairybrowser.plugins.readers import (
    DuplicatePageReaderPluginNameError,
    InvalidPageReaderPluginError,
    PageReaderContext,
    PageReaderCreator,
    PageReaderExecutor,
    PageReaderPluginLoader,
    PageReaderPluginLoadError,
    PageReaderPluginNotFoundError,
    PageReaderPluginRegistry,
)
from fairybrowser.storage import StoragePathSolver


def _valid_plugin_source(name: str = "sample") -> str:
    return f"""
from fairybrowser.plugins.readers import PageReaderCreator, PageReaderPlugin


class SamplePlugin(PageReaderPlugin):
    name = {name!r}

    def create(self):
        return PageReaderCreator.from_any(read=lambda page: "read")
"""


def test_reader_plugin_loader_lists_names_without_importing_plugin_code(tmp_path: Path):
    marker = tmp_path / "imported.txt"
    (tmp_path / "reader.py").write_text(
        f"""
from pathlib import Path
from fairybrowser.plugins.readers import PageReaderPlugin
Path({str(marker)!r}).write_text("imported")

class SampleReader(PageReaderPlugin):
    name = "sample"
    def create(self):
        raise RuntimeError("not called during listing")
""",
        encoding="utf-8",
    )
    loader = PageReaderPluginLoader(tmp_path)

    assert loader.list_plugins() == ("sample",)
    assert not marker.exists()


def test_reader_plugin_loader_loads_named_reader(tmp_path: Path):
    (tmp_path / "different-filename.py").write_text(_valid_plugin_source("stable-id"), encoding="utf-8")
    loader = PageReaderPluginLoader(tmp_path)

    reader = loader.load("stable-id")
    first_page = cast(Page, object())
    context = PageReaderContext()

    assert reader.select([first_page], context) is first_page
    assert reader.select([], context) is None
    assert reader.read(first_page, context) == "read"


@pytest.mark.parametrize(
    "import_module",
    (
        "fairybrowser.plugins",
        "fairybrowser.plugins.readers",
        "fairybrowser.plugins.readers.models",
    ),
)
def test_reader_plugin_loader_accepts_supported_base_import_modules(tmp_path: Path, import_module: str):
    (tmp_path / "imported.py").write_text(
        f'''
from fairybrowser.plugins.readers import PageReaderCreator
from {import_module} import PageReaderPlugin as PluginBase

class ImportedPlugin(PluginBase):
    name = "imported"
    def create(self): return PageReaderCreator.from_any(read=lambda _page: "imported")
''',
        encoding="utf-8",
    )
    registry = PageReaderPluginRegistry(tmp_path)

    assert registry.list_plugins() == ("imported",)
    assert registry.load("imported").read(cast(Page, object()), PageReaderContext()) == "imported"


def test_reader_plugin_loader_ignores_unsupported_base_import_module(tmp_path: Path):
    (tmp_path / "unsupported.py").write_text(
        '''
from fairybrowser import PageReaderPlugin

class UnsupportedPlugin(PageReaderPlugin):
    name = "unsupported"
''',
        encoding="utf-8",
    )
    registry = PageReaderPluginRegistry(tmp_path)

    assert registry.list_plugins() == ()
    with pytest.raises(PageReaderPluginNotFoundError):
        registry.load("unsupported")


def test_one_module_can_contain_multiple_plugin_kinds_and_entries(tmp_path: Path):
    from fairybrowser.invocation import InvocationContext
    from fairybrowser.plugins.invocation import InvocationPluginRegistry

    (tmp_path / "bundle.py").write_text(
        """
from fairybrowser.invocation import InvocationCreator
from fairybrowser.plugins.invocation import InvocationPlugin
from fairybrowser.plugins.readers import PageReaderCreator, PageReaderPlugin

class FirstReader(PageReaderPlugin):
    name = "shared"
    def create(self): return PageReaderCreator.from_any(read=lambda _page: "reader")

class SecondReader(PageReaderPlugin):
    name = "reader-two"
    def create(self): return PageReaderCreator.from_any(read=lambda _page: "reader two")

class SharedInvocation(InvocationPlugin):
    name = "shared"
    def create(self): return InvocationCreator.from_any(on_start=lambda *_args: None, on_completed=lambda _context: "invocation")
""",
        encoding="utf-8",
    )
    readers = PageReaderPluginRegistry(tmp_path)
    invocations = InvocationPluginRegistry(tmp_path)

    assert readers.list_plugins() == ("reader-two", "shared")
    assert invocations.list_plugins() == ("shared",)
    assert readers.load("shared").read(cast(Page, object()), PageReaderContext()) == "reader"
    assert invocations.load("shared").on_completed(cast(Page, object()), InvocationContext()) == "invocation"


def test_reader_plugin_registry_fetches_source_without_executing_it(tmp_path: Path):
    source = """
from fairybrowser.plugins.readers import PageReaderPlugin
raise RuntimeError("fetch must not execute plugin code")

class SourcePlugin(PageReaderPlugin):
    name = "source"
"""
    plugin_directory = tmp_path / "registry"
    plugin_directory.mkdir()
    (plugin_directory / "different-filename.py").write_text(source, encoding="utf-8")
    registry = PageReaderPluginRegistry(plugin_directory)

    assert registry.fetch("source") == source
    with pytest.raises(PageReaderPluginNotFoundError):
        registry.fetch("missing")


def test_page_reader_creator_normalizes_callback_signatures():
    class FakePage:
        def __init__(self, title: str):
            self._title = title

        def title(self) -> str:
            return self._title

    first_page = cast(Page, FakePage("first"))
    second_page = cast(Page, FakePage("second"))
    context = PageReaderContext(options={"selection": "last"})
    with pytest.raises(TypeError):
        cast(dict[str, object], context.options)["selection"] = "first"
    reader = PageReaderCreator.from_any(read=lambda page: page.title())
    context_reader = PageReaderCreator.from_any(
        read=lambda page, reader_context: f"{page.title()}:{reader_context.options['selection']}",
        select=lambda pages, reader_context: pages[-1]
        if reader_context.options["selection"] == "last"
        else pages[0],
    )

    assert reader.select([first_page, second_page], context) is first_page
    assert reader.select([], context) is None
    assert reader.read(second_page, context) == "second"
    assert context_reader.select([first_page, second_page], context) is second_page
    assert context_reader.select([], context) is None
    assert context_reader.read(second_page, context) == "second:last"


def test_reader_plugin_loader_rejects_missing_and_invalid_plugins(tmp_path: Path):
    (tmp_path / "invalid.py").write_text(
        """
from fairybrowser.plugins.readers import PageReaderPlugin

class Plugin(PageReaderPlugin):
    name = "invalid"
    def create_reader(self): return object()
""",
        encoding="utf-8",
    )
    loader = PageReaderPluginLoader(tmp_path)

    with pytest.raises(PageReaderPluginNotFoundError):
        loader.load("../invalid")
    with pytest.raises(PageReaderPluginNotFoundError):
        loader.load("missing")
    with pytest.raises(InvalidPageReaderPluginError, match="directly inherit"):
        loader.load("invalid")


def test_reader_plugin_loader_rejects_invalid_reader_result(tmp_path: Path):
    (tmp_path / "invalid-result.py").write_text(
        """
from fairybrowser.plugins.readers import PageReaderPlugin

class Plugin(PageReaderPlugin):
    name = "bad-result"
    def create(self): return object()
""",
        encoding="utf-8",
    )
    loader = PageReaderPluginLoader(tmp_path)

    with pytest.raises(InvalidPageReaderPluginError, match="PageReaderProtocol"):
        loader.load("bad-result")


def test_reader_plugin_loader_rejects_duplicate_names(tmp_path: Path):
    for filename in ("first.py", "second.py"):
        (tmp_path / filename).write_text(_valid_plugin_source("duplicate"), encoding="utf-8")
    loader = PageReaderPluginLoader(tmp_path)

    with pytest.raises(DuplicatePageReaderPluginNameError, match="duplicate"):
        loader.list_plugins()


def test_reader_plugin_loader_wraps_plugin_creation_errors(tmp_path: Path):
    (tmp_path / "broken.py").write_text(
        """
from fairybrowser.plugins.readers import PageReaderPlugin

class Plugin(PageReaderPlugin):
    name = "broken"
    def create(self): raise RuntimeError("failure")
""",
        encoding="utf-8",
    )
    loader = PageReaderPluginLoader(tmp_path)

    with pytest.raises(PageReaderPluginLoadError, match="Failed to create reader"):
        loader.load("broken")


def test_reader_plugin_registry_installs_and_checks_plugins(tmp_path: Path):
    registry = PageReaderPluginRegistry(tmp_path / "registry")

    installed = registry.install(_valid_plugin_source())

    assert installed == tmp_path / "registry" / "sample.py"
    assert registry.list_plugins() == ("sample",)
    assert registry.can_read("sample")
    with pytest.raises(FileExistsError):
        registry.install(_valid_plugin_source())


def test_reader_plugin_registry_installs_example(tmp_path: Path):
    plugin_directory = tmp_path / "registry"
    plugin_directory.mkdir()
    (plugin_directory / "example.py").write_text(_valid_plugin_source("example"), encoding="utf-8")
    registry = PageReaderPluginRegistry(plugin_directory)

    example_path = registry.install_example()
    reader = registry.load("example")

    class FakePage:
        def title(self) -> str:
            return "Example page"

    page = cast(Page, FakePage())
    context = PageReaderContext()
    assert example_path == plugin_directory / "example.py"
    assert reader.select([page], context) is page
    assert reader.read(page, context) == "Example page"


def test_reader_plugin_registry_reads_selected_page(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = """
from fairybrowser.plugins.readers import PageReaderCreator, PageReaderPlugin


class SamplePlugin(PageReaderPlugin):
    name = "sample"

    def create(self):
        def select(pages, context):
            context.state["selected_label"] = pages[-1].label
            return pages[-1] if pages else None

        def read(page, context):
            return f"{page.label}:{context.state['selected_label']}:{context.options['suffix']}"

        return PageReaderCreator.from_any(read=read, select=select)
"""
    (tmp_path / "reader.py").write_text(source, encoding="utf-8")
    registry = PageReaderPluginRegistry(tmp_path)
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
    def fake_sync_browser(*, info: BrowserInfo) -> Generator[SimpleNamespace]:
        assert info == browser_info
        yield browser

    monkeypatch.setattr("fairybrowser.plugins.readers.executor.sync_browser", fake_sync_browser)

    reader = registry.load("sample")
    assert PageReaderExecutor.from_any(reader).read(browser_info, options={"suffix": "read"}) == "second:second:read"
    assert registry.read("sample", browser_info, options={"suffix": "read"}) == "second:second:read"

    browser.contexts = [SimpleNamespace(pages=[])]
    assert registry.read("sample", browser_info, options={"suffix": "read"}) is None


def test_plugin_directories_are_nested_under_application_data_plugins(tmp_path: Path):
    data_home = tmp_path / "data"
    solver = StoragePathSolver(home_directory=tmp_path, data_home=data_home)
    plugins_directory = data_home / "fairybrowser" / "plugins"

    assert solver.invocation_plugins_directory() == plugins_directory / "invocations"
    assert solver.reader_plugins_directory() == plugins_directory / "readers"
