class PageReaderPluginError(Exception):
    """Base exception for reader plugin errors."""


class PageReaderPluginNotFoundError(PageReaderPluginError):
    """Raised when a named reader plugin cannot be found."""


class InvalidPageReaderPluginError(PageReaderPluginError):
    """Raised when a plugin does not implement the reader plugin contract."""


class DuplicatePageReaderPluginNameError(InvalidPageReaderPluginError):
    """Raised when multiple plugin files declare the same name."""


class PageReaderPluginLoadError(PageReaderPluginError):
    """Raised when loading a plugin module or creating its reader fails."""
