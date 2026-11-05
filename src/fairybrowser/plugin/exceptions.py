class PluginError(Exception):
    """Base exception for plugin infrastructure errors."""


class PluginNotFoundError(PluginError):
    """Raised when a named plugin module cannot be found."""


class PluginLoadError(PluginError):
    """Raised when a plugin module cannot be imported."""
