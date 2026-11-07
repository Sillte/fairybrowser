"""Reader-specific plugin contracts and implementations."""

from fairybrowser.plugins.readers.exceptions import (
    DuplicatePageReaderPluginNameError,
    InvalidPageReaderPluginError,
    PageReaderPluginError,
    PageReaderPluginLoadError,
    PageReaderPluginNotFoundError,
)
from fairybrowser.plugins.readers.executor import PageReaderExecutor
from fairybrowser.plugins.readers.loader import PageReaderPluginLoader
from fairybrowser.plugins.readers.models import (
    PageReaderContext,
    PageReaderCreator,
    PageReaderPlugin,
    PageReaderProtocol,
)
from fairybrowser.plugins.readers.registry import PageReaderPluginRegistry

__all__ = [
    "DuplicatePageReaderPluginNameError",
    "InvalidPageReaderPluginError",
    "PageReaderContext",
    "PageReaderCreator",
    "PageReaderExecutor",
    "PageReaderPluginError",
    "PageReaderPluginLoadError",
    "PageReaderPluginLoader",
    "PageReaderPluginNotFoundError",
    "PageReaderPlugin",
    "PageReaderPluginRegistry",
    "PageReaderProtocol",
]
