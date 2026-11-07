"""Reader-specific plugin contracts and implementations."""

from fairybrowser.plugins.readers.exceptions import (
    DuplicatePageReaderPluginNameError,
    InvalidPageReaderPluginError,
    PageReaderPluginError,
    PageReaderPluginLoadError,
    PageReaderPluginNotFoundError,
)
from fairybrowser.plugins.readers.loader import PageReaderPluginLoader
from fairybrowser.plugins.readers.models import (
    PageReaderContext,
    PageReaderCreator,
    PageReaderPluginProtocol,
    PageReaderProtocol,
)
from fairybrowser.plugins.readers.registry import PageReaderPluginRegistry

__all__ = [
    "DuplicatePageReaderPluginNameError",
    "InvalidPageReaderPluginError",
    "PageReaderContext",
    "PageReaderCreator",
    "PageReaderPluginError",
    "PageReaderPluginLoadError",
    "PageReaderPluginLoader",
    "PageReaderPluginNotFoundError",
    "PageReaderPluginProtocol",
    "PageReaderPluginRegistry",
    "PageReaderProtocol",
]
