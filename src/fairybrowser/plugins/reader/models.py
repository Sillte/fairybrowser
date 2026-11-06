from collections.abc import Sequence
from typing import ClassVar, Protocol, runtime_checkable

from playwright.sync_api import Page


@runtime_checkable
class ReaderProtocol(Protocol):
    """Operations provided by a reader implementation."""

    def select(self, pages: Sequence[Page]) -> Page | None:
        """Select a page to read, or return None when no page is suitable."""
        ...

    def read(self, page: Page) -> str:
        """Read the selected page as text."""
        ...


@runtime_checkable
class ReaderPluginProtocol(Protocol):
    """Contract for a named plugin that creates a reader."""

    name: ClassVar[str]

    def create(self) -> ReaderProtocol:
        """Create the reader implementation for this plugin."""
        ...
