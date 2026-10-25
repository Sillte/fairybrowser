from typing import Protocol

from playwright.sync_api import Browser, Page


class PageFinderProtocol(Protocol):
    def get_page(self, browser: Browser, pid: int) -> Page | None: ...
