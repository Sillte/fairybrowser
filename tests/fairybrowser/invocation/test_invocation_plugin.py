from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock

import pytest
from playwright.sync_api import Page

from fairybrowser.invocation import InvocationContext, InvocationCreator
from fairybrowser.plugins.invocation import (
    DuplicateInvocationPluginNameError,
    InvalidInvocationPluginError,
    InvocationPluginLoadError,
    InvocationPluginNotFoundError,
    InvocationPluginRegistry,
)


def _valid_plugin_source(result: str, name: str = "sample") -> str:
    return f'''
from fairybrowser.invocation import FetchTextStreamEventListener, InvocationCreator


class SamplePlugin:
    name = {name!r}

    def create(self):
        return InvocationCreator.from_any(
            on_start=lambda _input, _page: None,
            on_completed=lambda _context: {result!r},
            listeners=FetchTextStreamEventListener.from_any(lambda _event: None),
        )
'''


def test_plugin_registry_lists_literal_names_without_importing_plugin_code(tmp_path: Path):
    marker = tmp_path / "imported.txt"
    plugin_file = tmp_path / "implementation.py"
    plugin_file.write_text(
        f'''
from pathlib import Path
Path({str(marker)!r}).write_text("imported")

class NamedPlugin:
    name = "stable-id"
    def create(self):
        raise RuntimeError("not called during listing")
''',
        encoding="utf-8",
    )
    (tmp_path / "_private.py").write_text("value = 1", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("ignored", encoding="utf-8")
    registry = InvocationPluginRegistry(tmp_path)

    assert registry.list_plugins() == ("stable-id",)
    assert not marker.exists()


def test_plugin_registry_loads_structural_protocol_plugin(tmp_path: Path):
    (tmp_path / "different-filename.py").write_text(_valid_plugin_source("done", "stable-id"), encoding="utf-8")
    registry = InvocationPluginRegistry(tmp_path)

    invocation = registry.load("stable-id")

    assert isinstance(invocation, InvocationCreator)
    assert callable(invocation.start)


def test_plugin_registry_fetches_source_without_executing_it(tmp_path: Path):
    source = '''
raise RuntimeError("fetch must not execute plugin code")

class SourcePlugin:
    name = "source"
'''
    plugin_directory = tmp_path / "registry"
    plugin_directory.mkdir()
    (plugin_directory / "different-filename.py").write_text(source, encoding="utf-8")
    registry = InvocationPluginRegistry(plugin_directory)

    assert registry.fetch("source") == source
    with pytest.raises(InvocationPluginNotFoundError):
        registry.fetch("missing")


def test_plugin_registry_verifies_and_checks_executability(tmp_path: Path):
    (tmp_path / "valid.py").write_text(_valid_plugin_source("valid"), encoding="utf-8")
    registry = InvocationPluginRegistry(tmp_path)

    invocation = registry.verify("sample")

    assert callable(invocation.start)
    assert registry.can_execute("sample")
    assert not registry.can_execute("missing")


def test_plugin_registry_rejects_duplicate_names_before_import(tmp_path: Path):
    marker = tmp_path / "imported.txt"
    for filename in ("first.py", "second.py"):
        (tmp_path / filename).write_text(
            f'''
from pathlib import Path
Path({str(marker)!r}).write_text("imported")

class Plugin:
    name = "duplicate"
    def create(self):
        return None
''',
            encoding="utf-8",
        )
    registry = InvocationPluginRegistry(tmp_path)

    with pytest.raises(DuplicateInvocationPluginNameError, match="duplicate"):
        registry.list_plugins()
    assert not marker.exists()


def test_plugin_registry_rejects_multiple_named_classes_in_one_file(tmp_path: Path):
    (tmp_path / "ambiguous.py").write_text(
        '''
class FirstPlugin:
    name = "first"
    def create(self): return None

class SecondPlugin:
    name = "second"
    def create(self): return None
''',
        encoding="utf-8",
    )
    registry = InvocationPluginRegistry(tmp_path)

    with pytest.raises(InvalidInvocationPluginError, match="exactly one"):
        registry.list_plugins()


def test_plugin_registry_rejects_dynamic_plugin_name(tmp_path: Path):
    (tmp_path / "dynamic.py").write_text(
        '''
class Plugin:
    name = "dynamic".upper()
    def create(self): return None
''',
        encoding="utf-8",
    )
    registry = InvocationPluginRegistry(tmp_path)

    with pytest.raises(InvalidInvocationPluginError, match="literal string name"):
        registry.list_plugins()


def test_plugin_registry_rejects_missing_and_invalid_plugins(tmp_path: Path):
    (tmp_path / "invalid.py").write_text(
        '''
class Plugin:
    name = "invalid"
    def create_invocation(self): return None
''',
        encoding="utf-8",
    )
    registry = InvocationPluginRegistry(tmp_path)

    with pytest.raises(InvocationPluginNotFoundError):
        registry.load("../invalid")
    with pytest.raises(InvocationPluginNotFoundError):
        registry.load("missing")
    with pytest.raises(InvalidInvocationPluginError, match="callable create"):
        registry.load("invalid")


def test_plugin_registry_rejects_invalid_invocation_result(tmp_path: Path):
    (tmp_path / "invalid-result.py").write_text(
        '''
class Plugin:
    name = "bad-result"
    def create(self): return object()
''',
        encoding="utf-8",
    )
    registry = InvocationPluginRegistry(tmp_path)

    with pytest.raises(InvalidInvocationPluginError, match="InvocationProtocol"):
        registry.load("bad-result")


def test_plugin_registry_wraps_create_errors(tmp_path: Path):
    (tmp_path / "broken.py").write_text(
        '''
class Plugin:
    name = "broken"
    def create(self): raise RuntimeError("plugin failure")
''',
        encoding="utf-8",
    )
    registry = InvocationPluginRegistry(tmp_path)

    with pytest.raises(InvocationPluginLoadError) as error:
        registry.load("broken")

    assert isinstance(error.value.__cause__, RuntimeError)


def test_plugin_registry_installs_plugin_file(tmp_path: Path):
    source_file = tmp_path / "source-filename.py"
    source_file.write_text(_valid_plugin_source("file", "declared-id"), encoding="utf-8")
    registry = InvocationPluginRegistry(tmp_path / "registry")

    installed = registry.install(source_file)

    assert installed == tmp_path / "registry" / "declared-id.py"
    assert registry.list_plugins() == ("declared-id",)
    assert callable(registry.load("declared-id").on_completed)


def test_plugin_registry_installs_source_string_ending_in_py(tmp_path: Path):
    source = _valid_plugin_source("source", "inline").rstrip() + '\nmarker = ".py"'
    registry = InvocationPluginRegistry(tmp_path / "registry")

    installed = registry.install(source)

    assert installed == tmp_path / "registry" / "inline.py"
    assert registry.fetch("inline") == source


def test_plugin_registry_installs_example(tmp_path: Path):
    plugin_directory = tmp_path / "registry"
    plugin_directory.mkdir()
    (plugin_directory / "example.py").write_text(_valid_plugin_source("old", "example"), encoding="utf-8")
    registry = InvocationPluginRegistry(plugin_directory)

    example_path = registry.install_example()
    invocation = registry.load("example")
    context = InvocationContext()

    invocation.start("input", cast(Page, object()), context)

    assert example_path == plugin_directory / "example.py"
    assert context.completion_event.is_set()
    assert invocation.on_completed(cast(Page, object()), context) == "Example invocation completed"


def test_plugin_registry_installs_source_and_checks_duplicate_names(tmp_path: Path):
    registry = InvocationPluginRegistry(tmp_path / "registry")
    source = _valid_plugin_source("source", "inline")

    installed = registry.install(source)
    assert installed.name == "inline.py"

    with pytest.raises(FileExistsError):
        registry.install(_valid_plugin_source("duplicate", "inline"))
    with pytest.raises(InvalidInvocationPluginError):
        registry.install("value = 1")
    assert "source" in installed.read_text(encoding="utf-8")

    registry.install(_valid_plugin_source("replacement", "inline"), overwrite=True)
    assert "replacement" in installed.read_text(encoding="utf-8")
    assert registry.load("inline").on_completed(cast(Page, object()), InvocationContext()) == "replacement"


def test_plugin_registry_reloads_plugin_when_file_contents_change(tmp_path: Path):
    plugin_file = tmp_path / "reloadable.py"
    plugin_file.write_text(_valid_plugin_source("old", "reloadable"), encoding="utf-8")
    registry = InvocationPluginRegistry(tmp_path)

    first = registry.load("reloadable")
    assert first.on_completed(cast(Page, object()), InvocationContext()) == "old"

    plugin_file.write_text(_valid_plugin_source("new", "reloadable"), encoding="utf-8")

    reloaded = registry.load("reloadable")
    assert reloaded.on_completed(cast(Page, object()), InvocationContext()) == "new"


def test_plugin_registry_does_not_install_invalid_source(tmp_path: Path):
    registry = InvocationPluginRegistry(tmp_path / "registry")

    with pytest.raises(InvalidInvocationPluginError):
        registry.install("value = 1")

    assert list((tmp_path / "registry").glob("*.py")) == []


def test_plugin_registry_invokes_loaded_plugin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    (tmp_path / "sample.py").write_text(
        '''
from fairybrowser.invocation import InvocationCreator

class SamplePlugin:
    name = "sample"
    def create(self):
        def start(input, _page, context):
            context.state["input"] = input
            context.state["mode"] = context.options["mode"]
            context.complete()

        return InvocationCreator.from_any(
            on_start=start,
            on_completed=lambda context: (context.state["input"], context.state["mode"]),
            listeners=(),
        )
''',
        encoding="utf-8",
    )
    page = MagicMock(spec=Page)
    page.is_closed.return_value = False
    page.context.new_cdp_session.return_value = MagicMock()
    browser = SimpleNamespace(contexts=[SimpleNamespace(pages=[page])])

    @contextmanager
    def fake_sync_browser(**kwargs):
        assert kwargs["info"] is None
        yield browser

    monkeypatch.setattr("fairybrowser.invocation.models.sync_browser", fake_sync_browser)
    registry = InvocationPluginRegistry(tmp_path)
    input_data = {"url": "https://example.com"}

    result = registry.invoke("sample", input_data, options={"mode": "strict"})

    assert result == (input_data, "strict")
    page.context.new_cdp_session.assert_called_once_with(page)