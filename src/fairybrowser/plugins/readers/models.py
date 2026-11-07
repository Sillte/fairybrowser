from collections.abc import Sequence
from dataclasses import dataclass
from typing import Callable, ClassVar, Protocol, Self, runtime_checkable

from playwright.sync_api import Page


def _select_first_page(pages: Sequence[Page]) -> Page | None:
    return pages[0] if pages else None


@runtime_checkable
class PageReaderProtocol(Protocol):
    """Operations provided by a reader implementation."""

    def select(self, pages: Sequence[Page]) -> Page | None:
        """Select a page to read, or return None when no page is suitable."""
        ...

    def read(self, page: Page) -> str:
        """Read the selected page as text."""
        ...


@dataclass(frozen=True)
class PageReaderCreator:
    """Build a page reader from read and optional page-selection callbacks."""

    _read_callback: Callable[[Page], str]
    _select_page_callback: Callable[[Sequence[Page]], Page | None] = _select_first_page

    @classmethod
    def from_any(
        cls,
        read: Callable[[Page], str],
        select: Callable[[Sequence[Page]], Page | None] | None = None,
    ) -> Self:
        select_callback = _select_first_page if select is None else select
        return cls(_read_callback=read, _select_page_callback=select_callback)

    def select(self, pages: Sequence[Page]) -> Page | None:
        if not pages:
            return None
        return self._select_page_callback(pages)

    def read(self, page: Page) -> str:
        return self._read_callback(page)


@runtime_checkable
class PageReaderPluginProtocol(Protocol):
    """Contract for a named plugin that creates a reader."""

    name: ClassVar[str]

    def create(self) -> PageReaderProtocol:
        """Create the reader implementation for this plugin."""
        ...
