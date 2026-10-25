class InvocationPluginError(Exception):
    """Base exception for invocation plugin errors."""


class InvocationPluginNotFoundError(InvocationPluginError):
    """Raised when a named invocation plugin cannot be found."""


class InvalidInvocationPluginError(InvocationPluginError):
    """Raised when a plugin does not implement the invocation plugin contract."""


class InvocationPluginLoadError(InvocationPluginError):
    """Raised when loading a plugin module or creating its invocation fails."""
