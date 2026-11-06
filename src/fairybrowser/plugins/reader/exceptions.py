class ReaderPluginError(Exception):
    """Base exception for reader plugin errors."""


class ReaderPluginNotFoundError(ReaderPluginError):
    """Raised when a named reader plugin cannot be found."""


class InvalidReaderPluginError(ReaderPluginError):
    """Raised when a plugin does not implement the reader plugin contract."""


class DuplicateReaderPluginNameError(InvalidReaderPluginError):
    """Raised when multiple plugin files declare the same name."""


class ReaderPluginLoadError(ReaderPluginError):
    """Raised when loading a plugin module or creating its reader fails."""
