# Plugin Specification

## Trust and execution

Invocation and reader plugins are trusted local Python code, not sandboxed extensions. Loading a plugin executes its module, plugin class constructor, and `create()` method in the current process. Install or use only code from trusted sources. `list_plugins()` parses source metadata without importing plugin modules.

## Discovery and storage

Registries discover top-level `.py` files in their plugin directory. Each plugin module must contain exactly one top-level class with a literal string `name` that follows the plugin-name format (`A-Z`, `a-z`, digits, `_`, and `-`, beginning with a letter or digit). Names must be unique within a plugin directory. The filename does not determine the plugin name.

By default, plugin files are stored under the application data directory resolved by `StoragePathSolver`:

- `<application_data_directory>/plugins/invocations/`
- `<application_data_directory>/plugins/readers/`

`list_plugins()` returns the sorted declared names without executing plugin code.

## Contracts

A plugin class has a literal string `name` class attribute and a `create()` method. For invocation plugins, `create()` returns an `InvocationProtocol` with `select(pages) -> Page`, `start(input, page, context)`, a `listeners` property, and `on_completed(page, context) -> result`.

For reader plugins, `create()` returns a `ReaderProtocol` with:

```python
class ReaderProtocol(Protocol):
    def select(self, pages: Sequence[Page]) -> Page | None: ...
    def read(self, page: Page) -> str: ...
```

Reader registries return `None` when the selected reader finds no suitable page. Runtime checks confirm required members are present and callable; they do not guarantee plugin behavior or successful page operations.

## Main usage

```python
from fairybrowser.models import BrowserInfo
from fairybrowser.plugins.invocation import InvocationPluginRegistry
from fairybrowser.plugins.reader import ReaderPluginRegistry

invocations = InvocationPluginRegistry()
result = invocations.invoke("example", input=payload)

readers = ReaderPluginRegistry()
text = readers.read("example", BrowserInfo())  # str, or None when no page is selected
```

Both registries provide `list_plugins()`, `load(name)`, `verify(name)`, `install(source, overwrite=False)`, and `make_example()`. `make_example()` creates the plugin directory if needed, writes a small, loadable plugin to `example.py`, overwrites any existing file at that path, and returns the file path. The generated plugin is specific to the registry type: an invocation example for `InvocationPluginRegistry` or a reader example for `ReaderPluginRegistry`. `InvocationPluginRegistry` also provides `can_execute(name)` and `invoke(name, input=...)`; `ReaderPluginRegistry` provides `can_read(name)` and `read(name, browser_info)`. `read()` opens the managed browser with `sync_browser`, passes all open pages across its contexts to the reader's `select()`, then reads the selected page; it returns `None` when no page is selected. `install()` accepts a `.py` path or Python source string and validates it by executing the plugin; overwriting an existing plugin requires `overwrite=True`.