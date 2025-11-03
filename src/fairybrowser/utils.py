from playwright.sync_api import Browser, Page

import psutil
from fairybrowser.process_utils import get_visible_windows


def get_page(browser: Browser, pid: int) -> Page | None:
    """Get the `page`, which follows the rules.
    1. its condition meets the given argumens, if any.
    2. the active pages.
      """
    os_infos = get_visible_windows()
    process = psutil.Process()
    descendant_pids = {p.pid for p in process.children(recursive=True)}
    descendant_pids.add(pid)
    
    infos = [info for info in os_infos if info.pid in descendant_pids]  
    if not infos:
        return None
    target_info = infos[0]
    window_title = target_info.title

    for context in browser.contexts:
        for page in context.pages:
            client = context.new_cdp_session(page)
            try:
                window_info = client.send("Browser.getWindowForTarget")
                bounds = window_info.get("bounds", {})
                print(bounds, window_info)
            except Exception:
                # fallback: some browsers (Edge) might not support this
                try:
                    targets = client.send("Target.getTargets")["targetInfos"]
                    bounds = {"windowState": "normal"} if targets else {}
                except Exception:
                    continue

            if bounds.get("windowState") in {"normal", "maximized"} and window_title.startswith(page.title()):
                return page
    return None
