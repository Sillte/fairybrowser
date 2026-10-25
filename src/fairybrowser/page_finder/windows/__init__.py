import psutil
from playwright.sync_api import Browser, Page

from fairybrowser.page_finder.protocol import PageFinderProtocol
from fairybrowser.page_finder.windows.process_utils import get_visible_windows


class WindowsPageFinder(PageFinderProtocol):
    def get_page(self, browser: Browser, pid: int) -> Page | None:
        """Find a page matching a visible browser window."""
        os_infos = get_visible_windows()
        process = psutil.Process()
        descendant_pids = {child.pid for child in process.children(recursive=True)}
        descendant_pids.add(pid)

        infos = [info for info in os_infos if info.pid in descendant_pids]
        if not infos:
            return None

        for target_info in infos:
            window_title = target_info.title
            for context in browser.contexts:
                for page in context.pages:
                    client = context.new_cdp_session(page)
                    try:
                        window_info = client.send("Browser.getWindowForTarget")
                        bounds = window_info.get("bounds", {})
                    except Exception:
                        # Some browsers, such as Edge, might not support this command.
                        try:
                            targets = client.send("Target.getTargets")["targetInfos"]
                            bounds = {"windowState": "normal"} if targets else {}
                        except Exception:
                            continue

                    if bounds.get("windowState") in {"normal", "maximized"} and window_title.startswith(page.title()):
                        return page
        return None
