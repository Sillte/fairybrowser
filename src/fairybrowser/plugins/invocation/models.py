from typing import ClassVar, Protocol, runtime_checkable

from fairybrowser.invocation.models import InvocationProtocol


@runtime_checkable
class InvocationPluginProtocol[InputT, ResultT](Protocol):
    """Contract for a named plugin that creates an invocation."""

    name: ClassVar[str]

    def create(self) -> InvocationProtocol[InputT, ResultT]:
        """Create the invocation implementation for this plugin."""
        ...
