"""Reader-specific plugin contracts and implementations."""

from fairybrowser.plugins.reader.exceptions import (
    DuplicateReaderPluginNameError,
    InvalidReaderPluginError,
    ReaderPluginError,
    ReaderPluginLoadError,
    ReaderPluginNotFoundError,
)
from fairybrowser.plugins.reader.loader import ReaderPluginLoader
from fairybrowser.plugins.reader.models import ReaderPluginProtocol, ReaderProtocol
from fairybrowser.plugins.reader.registry import ReaderPluginRegistry

__all__ = [
    "DuplicateReaderPluginNameError",
    "InvalidReaderPluginError",
    "ReaderPluginError",
    "ReaderPluginLoadError",
    "ReaderPluginLoader",
    "ReaderPluginNotFoundError",
    "ReaderPluginProtocol",
    "ReaderPluginRegistry",
    "ReaderProtocol",
]
