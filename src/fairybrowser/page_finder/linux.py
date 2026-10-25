from playwright.sync_api import Browser, Page

from fairybrowser.page_finder.protocol import PageFinderProtocol


class LinuxPageFinder(PageFinderProtocol):
    def get_page(self, browser: Browser, pid: int) -> Page | None:
        """Return the first page in browser context and page order."""
        del pid
        for context in browser.contexts:
            if context.pages:
                return context.pages[0]
        return None
