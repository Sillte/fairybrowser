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

For reader plugins, `create()` returns a `PageReaderProtocol` with:

```python
class PageReaderProtocol(Protocol):
    def select(self, pages: Sequence[Page], context: PageReaderContext) -> Page | None: ...
    def read(self, page: Page, context: PageReaderContext) -> str: ...
```

`PageReaderContext` provides per-read `state` and read-only `options`, shared between `select()` and `read()`. `PageReaderPluginRegistry.read()` creates the context and accepts per-call options through `options=...`. `PageReaderCreator.from_any(read, select=None)` accepts one-argument callbacks or callbacks that also receive the context; it normalizes both forms to the protocol. By default, it selects the first page, or returns `None` for an empty page sequence. Reader registries also return `None` when the selected reader finds no suitable page. Runtime checks confirm required members are present and callable; they do not guarantee plugin behavior or successful page operations. `PageReaderExecutor(reader).read(browser_info=None, options=None)` runs an already-created reader without loading it through a registry: it creates the per-read context, opens the managed browser, lets the reader select from its open pages, and reads the selected page. It returns `None` when no page is selected and raises `RuntimeError` if the reader selects a closed page or one outside the managed browser. It does not install or sandbox the reader.

## Main usage

```python
from fairybrowser.models import BrowserInfo
from fairybrowser.plugins.invocation import InvocationPluginRegistry
from fairybrowser.plugins.readers import PageReaderPluginRegistry

invocations = InvocationPluginRegistry()
result = invocations.invoke("example", input=payload)

readers = PageReaderPluginRegistry()
text = readers.read("example", BrowserInfo())  # str, or None when no page is selected
```

Both registries provide `list_plugins()`, `load(name)`, `verify(name)`, `fetch(name)`, `install(source, overwrite=False)`, and `install_example()`. `fetch()` returns the source code of the named plugin as a string without importing or executing it. `install_example()` reads the registry type's bundled `example.py` template and installs it through `install()` for validation, replacing any existing plugin named `example`; it returns the installed file path. `InvocationPluginRegistry` also provides `can_execute(name)` and `invoke(name, input=...)`; `PageReaderPluginRegistry` provides `can_read(name)` and `read(name, browser_info, options=None)`. The options are copied into the `PageReaderContext` as a read-only mapping. `read()` opens the managed browser with `sync_browser`, passes all open pages across its contexts to the reader's `select()`, then reads the selected page; it returns `None` when no page is selected. `install()` accepts a `Path` to a `.py` file or a Python source string and validates it by executing the plugin. String arguments are always treated as source code, even when they end in `.py`; overwriting an existing plugin requires `overwrite=True`.