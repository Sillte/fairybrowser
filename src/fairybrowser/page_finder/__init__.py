import sys

from fairybrowser.page_finder.protocol import PageFinderProtocol


def create_page_finder() -> PageFinderProtocol:
    """Create the page finder implementation for the current operating system."""
    if sys.platform == "win32":
        from fairybrowser.page_finder.windows import WindowsPageFinder

        return WindowsPageFinder()
    if sys.platform.startswith("linux"):
        from fairybrowser.page_finder.linux import LinuxPageFinder

        return LinuxPageFinder()
    raise RuntimeError(f"Page finding is not supported on {sys.platform}.")


__all__ = ["PageFinderProtocol", "create_page_finder"]
