from abc import ABC, abstractmethod
from typing import ClassVar

from fairybrowser.invocation.models import InvocationProtocol


class InvocationPlugin[InputT, ResultT](ABC):
    """Abstract entry point for a named invocation plugin."""

    name: ClassVar[str]

    @abstractmethod
    def create(self) -> InvocationProtocol[InputT, ResultT]:
        """Create the invocation implementation for this plugin."""
