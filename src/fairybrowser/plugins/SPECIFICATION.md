# Plugin Specification

## Trust and execution

Invocation and reader plugins are trusted local Python code, not sandboxed extensions. `list_plugins()` parses source metadata without importing plugin modules. Loading or installing a plugin executes its module, plugin class constructor, and `create()` method in the current process. Install or use only code from trusted sources.

## Discovery and storage

Registries discover top-level `.py` files in their plugin directory. A module may define any number of plugin classes, including both invocation and reader plugins, along with helper classes. The filename does not determine plugin names.

Each plugin class must directly inherit from the corresponding public abstract base class:

```python
from fairybrowser.plugins.invocation import InvocationPlugin
from fairybrowser.plugins.readers import PageReaderPlugin

class MyInvocationPlugin(InvocationPlugin):
    name = "my-invocation"

    def create(self): ...

class MyPageReaderPlugin(PageReaderPlugin):
    name = "my-reader"

    def create(self): ...
```

For AST discovery, the base class must be imported at module level using `from ... import ...`; import aliases are supported. Invocation plugins may import `InvocationPlugin` from `fairybrowser.plugins`, `fairybrowser.plugins.invocation`, or `fairybrowser.plugins.invocation.models`. Reader plugins may import `PageReaderPlugin` from `fairybrowser.plugins`, `fairybrowser.plugins.readers`, or `fairybrowser.plugins.readers.models`. Imports from `fairybrowser` itself and all other module paths are not plugin declarations. The class must directly name that imported base in its bases; generic specialization such as `InvocationPlugin[InputT, ResultT]` is supported. Indirect inheritance, qualified attribute bases, dynamically generated bases, and conditional or nested imports are not plugin declarations. `name` must be declared once in the class body as a literal string following the plugin-name format (`A-Z`, `a-z`, digits, `_`, and `-`, beginning with a letter or digit). Helper classes that do not directly inherit from a plugin base are ignored.

Each registry recognizes only its own base class. Names must be unique among plugins of the same kind across all files in that registry; a reader and invocation may have the same name. `list_plugins()` returns sorted names without executing plugin code. AST discovery identifies candidates; loading additionally confirms that the class directly inherits from the actual ABC, is concrete, and returns a valid implementation.

By default, plugin files are stored under the application data directory resolved by `StoragePathSolver`:

- `<application_data_directory>/plugins/invocations/`
- `<application_data_directory>/plugins/readers/`

Both registries accept an explicit `plugin_directory`, so they can also inspect a common source directory while exposing separate invocation and reader APIs.

## Contracts

`InvocationPlugin.create()` returns an `InvocationProtocol` with `select(pages) -> Page`, `start(input, page, context)`, a `listeners` property, and `on_completed(page, context) -> result`.

`PageReaderPlugin.create()` returns a `PageReaderProtocol` with:

```python
class PageReaderProtocol(Protocol):
    def select(self, pages: Sequence[Page], context: PageReaderContext) -> Page | None: ...
    def read(self, page: Page, context: PageReaderContext) -> str: ...
```

`PageReaderContext` provides per-read `state` and read-only `options`, shared between `select()` and `read()`. `PageReaderPluginRegistry.read()` creates the context and accepts per-call options through `options=...`. `PageReaderCreator.from_any(read, select=None)` accepts one-argument callbacks or callbacks that also receive the context; it normalizes both forms to the protocol. By default, it selects the first page, or returns `None` for an empty page sequence. Reader registries also return `None` when the selected reader finds no suitable page. Runtime checks validate the ABC and required result-protocol members; they do not guarantee plugin behavior or successful page operations. `PageReaderExecutor(reader).read(browser_info=None, options=None)` runs an already-created reader without loading it through a registry: it creates the per-read context, opens the managed browser, lets the reader select from its open pages, and reads the selected page. It returns `None` when no page is selected and raises `RuntimeError` if the reader selects a closed page or one outside the managed browser. It does not install or sandbox the reader.

## Main usage

```python
from fairybrowser.models import BrowserInfo
from fairybrowser.plugins.invocation import (
    InvocationContext,
    InvocationCreator,
    InvocationExecutor,
    InvocationPlugin,
    InvocationPluginRegistry,
)
from fairybrowser.plugins.readers import PageReaderPluginRegistry

invocations = InvocationPluginRegistry()
result = invocations.invoke("example", input=payload)

readers = PageReaderPluginRegistry()
text = readers.read("example", BrowserInfo())  # str, or None when no page is selected
```

Both registries provide `list_plugins()`, `load(name)`, `verify(name)`, `fetch(name)`, `install(source, overwrite=False, filename=None)`, and `install_example()`. `fetch()` returns the complete source file containing the named plugin without importing or executing it. `install_example()` reads the registry type's bundled `example.py` template and installs it through `install()` for validation, replacing any existing plugin named `example`; it returns the installed file path. `InvocationPluginRegistry` also provides `can_execute(name)` and `invoke(name, input=...)`; `PageReaderPluginRegistry` provides `can_read(name)` and `read(name, browser_info, options=None)`. The options are copied into the `PageReaderContext` as a read-only mapping. `read()` opens the managed browser with `sync_browser`, passes all open pages across its contexts to the reader's `select()`, then reads the selected page; it returns `None` when no page is selected. `install()` accepts a `Path` to a `.py` file or a Python source string and validates all plugins of the registry's kind in the file. A source string containing multiple plugins of that kind requires `filename`; a source `Path` uses its basename in that case. String arguments are always treated as source code, even when they end in `.py`; overwriting an existing bundle requires `overwrite=True` and the existing bundle filename.