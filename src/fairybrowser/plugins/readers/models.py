from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from inspect import signature
from types import MappingProxyType
from typing import Any, Callable, ClassVar, Protocol, Self, cast, runtime_checkable

from playwright.sync_api import Page


@dataclass(frozen=True)
class PageReaderContext:
    """Per-read state and immutable options shared by page selection and reading."""

    state: dict[str, Any] = field(default_factory=dict)
    options: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "options", MappingProxyType(dict(self.options)))


def _select_first_page(pages: Sequence[Page]) -> Page | None:
    return pages[0] if pages else None


@runtime_checkable
class PageReaderProtocol(Protocol):
    """Operations provided by a reader implementation."""

    def select(self, pages: Sequence[Page], context: PageReaderContext) -> Page | None:
        """Select a page to read, or return None when no page is suitable."""
        ...

    def read(self, page: Page, context: PageReaderContext) -> str:
        """Read the selected page as text."""
        ...


type _ReadCallback = Callable[[Page], str] | Callable[[Page, PageReaderContext], str]
type _ContextReadCallback = Callable[[Page, PageReaderContext], str]
type _SelectCallback = (
    Callable[[Sequence[Page]], Page | None] | Callable[[Sequence[Page], PageReaderContext], Page | None]
)
type _ContextSelectCallback = Callable[[Sequence[Page], PageReaderContext], Page | None]


@dataclass(frozen=True)
class PageReaderCreator:
    """Build a page reader from callbacks, with or without a per-read context."""

    _read_callback: _ContextReadCallback
    _select_page_callback: _ContextSelectCallback

    @classmethod
    def from_any(
        cls,
        read: _ReadCallback,
        select: _SelectCallback | None = None,
    ) -> Self:
        select_callback = _select_first_page if select is None else select
        return cls(
            _read_callback=cls._resolve_read_callback(read),
            _select_page_callback=cls._resolve_select_callback(select_callback),
        )

    @staticmethod
    def _resolve_read_callback(callback: _ReadCallback) -> _ContextReadCallback:
        callback_signature = signature(callback)
        try:
            callback_signature.bind(None, None)
        except TypeError:
            callback_signature.bind(None)
            one_argument = cast(Callable[[Page], str], callback)

            def normalized(page: Page, context: PageReaderContext) -> str:
                del context
                return one_argument(page)

            return cast(_ContextReadCallback, normalized)
        return cast(_ContextReadCallback, callback)

    @staticmethod
    def _resolve_select_callback(callback: _SelectCallback) -> _ContextSelectCallback:
        callback_signature = signature(callback)
        try:
            callback_signature.bind(None, None)
        except TypeError:
            callback_signature.bind(None)
            one_argument = cast(Callable[[Sequence[Page]], Page | None], callback)

            def normalized(pages: Sequence[Page], context: PageReaderContext) -> Page | None:
                del context
                return one_argument(pages)

            return cast(_ContextSelectCallback, normalized)
        return cast(_ContextSelectCallback, callback)

    def select(self, pages: Sequence[Page], context: PageReaderContext) -> Page | None:
        if not pages:
            return None
        return self._select_page_callback(pages, context)

    def read(self, page: Page, context: PageReaderContext) -> str:
        return self._read_callback(page, context)


@runtime_checkable
class PageReaderPluginProtocol(Protocol):
    """Contract for a named plugin that creates a reader."""

    name: ClassVar[str]

    def create(self) -> PageReaderProtocol:
        """Create the reader implementation for this plugin."""
        ...
