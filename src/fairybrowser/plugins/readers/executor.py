from collections.abc import Mapping
from typing import Self

from fairybrowser.models import BrowserInfo
from fairybrowser.plugins.readers.models import PageReaderContext, PageReaderProtocol
from fairybrowser.runners import sync_browser


class PageReaderExecutor:
    """Run a page reader against pages in a managed browser."""

    def __init__(self, reader: PageReaderProtocol) -> None:
        self._reader = reader

    @classmethod
    def from_any(cls, reader: PageReaderProtocol) -> Self:
        return cls(reader)

    def read(
        self,
        browser_info: BrowserInfo | str | None = None,
        *,
        options: Mapping[str, object] | None = None,
    ) -> str | None:
        """Select and read a page, returning None when no page is selected."""
        context = PageReaderContext(options={} if options is None else options)
        with sync_browser(info=browser_info) as browser:
            pages = tuple(
                page for browser_context in browser.contexts for page in browser_context.pages if not page.is_closed()
            )
            page = self._reader.select(pages, context)
            if page is None:
                return None
            if page.is_closed() or not any(
                page is candidate
                for browser_context in browser.contexts
                for candidate in browser_context.pages
                if not candidate.is_closed()
            ):
                raise RuntimeError("The reader must select an open page from the managed browser.")
            return self._reader.read(page, context)
