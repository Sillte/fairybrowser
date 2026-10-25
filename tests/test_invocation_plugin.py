from contextlib import contextmanager
from pathlib import Path
from typing import cast
from unittest.mock import MagicMock

import pytest
from playwright.sync_api import Page

from fairybrowser.invocation import InvocationConfiguration, InvocationContext, InvocationCreator
from fairybrowser.invocation.plugin import (
    InvalidInvocationPluginError,
    InvocationPlugin,
    InvocationPluginLoadError,
    InvocationPluginNotFoundError,
    InvocationPluginRegistry,
)


def _valid_plugin_source(result: str) -> str:
    return f"""
from fairybrowser.invocation import FetchTextStreamEventListener, InvocationCreator
from fairybrowser.invocation.plugin import InvocationPlugin


class InstalledInvocation(InvocationPlugin):
    def create_invocation(self):
        return InvocationCreator.from_any(
            on_start=lambda _input, _page: None,
            on_completed=lambda _context: {result!r},
            listeners=FetchTextStreamEventListener.from_any(lambda _event: None),
        )
"""


def test_invocation_plugin_execute_forwards_configuration_and_output_folder(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    received = {}

    class FakeExecutor:
        def invoke(self, input, *, configuration, output_folder):
            received["call"] = (input, configuration, output_folder)
            return "result"

    def create_executor(invocation):
        received["invocation"] = invocation
        return FakeExecutor()

    monkeypatch.setattr("fairybrowser.invocation.plugin.models.InvocationExecutor.from_any", create_executor)

    class ExamplePlugin(InvocationPlugin[str, str]):
        def create_invocation(self):
            return InvocationCreator.from_any(
                on_start=lambda _input, _page: None,
                on_completed=lambda _context: "unused",
                listeners=(),
            )

    configuration = InvocationConfiguration(timeout=10)
    output_folder = tmp_path / "logs"

    result = ExamplePlugin.execute("hello", configuration, output_folder=output_folder)

    assert result == "result"
    assert received["call"] == ("hello", configuration, output_folder)
    assert isinstance(received["invocation"], InvocationCreator)


def test_plugin_registry_lists_and_loads_invocations(tmp_path: Path):
    plugin_file = tmp_path / "sample.py"
    plugin_file.write_text(
        """
from fairybrowser.invocation import FetchTextStreamEventListener, InvocationCreator
from fairybrowser.invocation.plugin import InvocationPlugin


class SampleCollector(InvocationPlugin):
    def create_invocation(self):
        return InvocationCreator.from_any(
            on_start=lambda _input, _page: None,
            on_completed=lambda _context: "done",
            listeners=FetchTextStreamEventListener.from_any(lambda _event: None),
        )
""",
        encoding="utf-8",
    )
    (tmp_path / "_private.py").write_text("", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("", encoding="utf-8")
    registry = InvocationPluginRegistry(tmp_path)

    assert registry.list_plugins() == ("sample",)
    assert callable(registry.load("sample").start)


def test_plugin_registry_verifies_and_checks_executability(tmp_path: Path):
    (tmp_path / "valid.py").write_text(_valid_plugin_source("valid"), encoding="utf-8")
    registry = InvocationPluginRegistry(tmp_path)

    invocation = registry.verify("valid")

    assert callable(invocation.start)
    assert registry.can_execute("valid")
    assert not registry.can_execute("missing")


def test_plugin_registry_verification_preserves_load_errors(tmp_path: Path):
    (tmp_path / "invalid.py").write_text("value = 1", encoding="utf-8")
    registry = InvocationPluginRegistry(tmp_path)

    with pytest.raises(InvalidInvocationPluginError):
        registry.verify("invalid")

    assert not registry.can_execute("invalid")


def test_plugin_registry_loads_decorated_factory_function(tmp_path: Path):
    (tmp_path / "factory.py").write_text(
        """
from fairybrowser.invocation import FetchTextStreamEventListener, InvocationCreator
from fairybrowser.invocation.plugin import invocation_plugin


@invocation_plugin
def build_collector():
    return InvocationCreator.from_any(
        on_start=lambda _input, _page: None,
        on_completed=lambda _context: "done",
        listeners=FetchTextStreamEventListener.from_any(lambda _event: None),
    )


def helper():
    return None
""",
        encoding="utf-8",
    )
    registry = InvocationPluginRegistry(tmp_path)

    assert callable(registry.load("factory").start)


def test_plugin_registry_rejects_ambiguous_candidates(tmp_path: Path):
    (tmp_path / "ambiguous.py").write_text(
        """
from fairybrowser.invocation.plugin import InvocationPlugin


class FirstPlugin(InvocationPlugin):
    def create_invocation(self):
        return None


class SecondPlugin(InvocationPlugin):
    def create_invocation(self):
        return None
""",
        encoding="utf-8",
    )
    registry = InvocationPluginRegistry(tmp_path)

    with pytest.raises(InvalidInvocationPluginError, match="found 2"):
        registry.load("ambiguous")


def test_plugin_registry_rejects_missing_and_non_subclass_plugins(tmp_path: Path):
    (tmp_path / "invalid.py").write_text(
        """
class Plugin:
    def create_invocation(self):
        return None
""",
        encoding="utf-8",
    )
    registry = InvocationPluginRegistry(tmp_path)

    with pytest.raises(InvocationPluginNotFoundError):
        registry.load("../invalid")
    with pytest.raises(InvocationPluginNotFoundError):
        registry.load("missing")
    with pytest.raises(InvalidInvocationPluginError, match="found 0"):
        registry.load("invalid")


def test_plugin_registry_rejects_abstract_plugin_classes(tmp_path: Path):
    (tmp_path / "abstract.py").write_text(
        """
from fairybrowser.invocation.plugin import InvocationPlugin


class IncompletePlugin(InvocationPlugin):
    pass
""",
        encoding="utf-8",
    )
    registry = InvocationPluginRegistry(tmp_path)

    with pytest.raises(InvalidInvocationPluginError, match="found 0"):
        registry.load("abstract")


def test_plugin_registry_rejects_invalid_invocation_creator(tmp_path: Path):
    (tmp_path / "invalid_creator.py").write_text(
        """
from fairybrowser.invocation.plugin import InvocationPlugin


class Invocation:
    start = None
    listeners = ()

    def on_completed(self, page, context):
        return None


class InvalidCreatorPlugin(InvocationPlugin):
    def create_invocation(self):
        return Invocation()
""",
        encoding="utf-8",
    )
    registry = InvocationPluginRegistry(tmp_path)

    with pytest.raises(InvalidInvocationPluginError, match="InvocationProtocol"):
        registry.load("invalid_creator")


def test_plugin_registry_wraps_plugin_load_errors(tmp_path: Path):
    (tmp_path / "broken.py").write_text(
        """
from fairybrowser.invocation.plugin import InvocationPlugin


class BrokenPlugin(InvocationPlugin):
    def create_invocation(self):
        raise RuntimeError("plugin failure")
""",
        encoding="utf-8",
    )
    registry = InvocationPluginRegistry(tmp_path)

    with pytest.raises(InvocationPluginLoadError) as error:
        registry.load("broken")

    assert isinstance(error.value.__cause__, RuntimeError)


@pytest.mark.parametrize("as_string", [False, True])
def test_plugin_registry_installs_plugin_file(tmp_path: Path, as_string: bool):
    source_file = tmp_path / "from_file.py"
    source_file.write_text(_valid_plugin_source("file"), encoding="utf-8")
    source: Path | str = str(source_file) if as_string else source_file
    registry = InvocationPluginRegistry(tmp_path / "registry")

    installed = registry.install(source)

    assert installed == tmp_path / "registry" / "from_file.py"
    assert registry.list_plugins() == ("from_file",)
    assert callable(registry.load("from_file").on_completed)


def test_plugin_registry_installs_source_with_name_and_checks_duplicates(tmp_path: Path):
    registry = InvocationPluginRegistry(tmp_path / "registry")
    source = _valid_plugin_source("source")

    with pytest.raises(ValueError, match="name is required"):
        registry.install(source)

    installed = registry.install(source, name="inline")
    assert installed.name == "inline.py"

    with pytest.raises(FileExistsError):
        registry.install(_valid_plugin_source("duplicate"), name="inline")
    with pytest.raises(InvalidInvocationPluginError):
        registry.install("value = 1", name="inline", overwrite=True)
    assert "source" in installed.read_text(encoding="utf-8")

    registry.install(_valid_plugin_source("replacement"), name="inline", overwrite=True)
    assert "replacement" in installed.read_text(encoding="utf-8")
    assert registry.load("inline").on_completed(cast(Page, object()), InvocationContext()) == "replacement"


def test_plugin_registry_reloads_plugin_when_file_contents_change(tmp_path: Path):
    plugin_file = tmp_path / "reloadable.py"
    plugin_file.write_text(_valid_plugin_source("old"), encoding="utf-8")
    registry = InvocationPluginRegistry(tmp_path)

    first = registry.load("reloadable")
    assert first.on_completed(cast(Page, object()), InvocationContext()) == "old"

    plugin_file.write_text(_valid_plugin_source("new"), encoding="utf-8")

    reloaded = registry.load("reloadable")
    assert reloaded.on_completed(cast(Page, object()), InvocationContext()) == "new"


def test_plugin_registry_does_not_install_invalid_source(tmp_path: Path):
    registry = InvocationPluginRegistry(tmp_path / "registry")

    with pytest.raises(InvalidInvocationPluginError, match="found 0"):
        registry.install("value = 1", name="invalid")

    assert not (tmp_path / "registry" / "invalid.py").exists()


def test_plugin_registry_treats_py_suffixed_string_as_path(tmp_path: Path):
    registry = InvocationPluginRegistry(tmp_path / "registry")

    with pytest.raises(FileNotFoundError):
        registry.install(str(tmp_path / "missing.py"))


def test_plugin_registry_invokes_loaded_plugin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    (tmp_path / "sample.py").write_text(
        """
from fairybrowser.invocation import InvocationCreator
from fairybrowser.invocation.plugin import InvocationPlugin


class SamplePlugin(InvocationPlugin):
    def create_invocation(self):
        def start(input, _page, context):
            context.state["input"] = input
            context.complete()

        return InvocationCreator.from_any(
            on_start=start,
            on_completed=lambda context: context.state["input"],
            listeners=(),
        )
""",
        encoding="utf-8",
    )
    page = MagicMock(spec=Page)
    page.context.new_cdp_session.return_value = MagicMock()

    @contextmanager
    def fake_sync_page(**kwargs):
        assert kwargs == {"browser_info": None}
        yield page

    monkeypatch.setattr("fairybrowser.invocation.models.sync_page", fake_sync_page)
    registry = InvocationPluginRegistry(tmp_path)
    input_data = {"url": "https://example.com"}

    result = registry.invoke("sample", input_data)

    assert result == input_data
    page.context.new_cdp_session.assert_called_once_with(page)
