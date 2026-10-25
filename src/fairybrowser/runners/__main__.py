from fairybrowser import BrowserInfo
from fairybrowser.monitors import get_pid
from fairybrowser.page_finder.windows.process_utils import to_foreground
from fairybrowser.runners import sync_page


def main() -> None:
    info = BrowserInfo(type="edge", spawn="webdriver")
    with sync_page(info) as page:
        pid = get_pid(info)
        assert pid is not None
        print("Return", page.title())
        to_foreground(pid, with_maximize=True)


if __name__ == "__main__":
    main()
