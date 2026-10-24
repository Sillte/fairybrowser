from fairybrowser import sync_page
from fairybrowser.devtools import DevtoolsService
from fairybrowser.devtools.models.fetch_text_stream_event import FetchTextStreamEvent
from fairybrowser.devtools.models.policy import DevtoolsLogPolicy

address = "https://chatgpt.com/"


def predicate(event: FetchTextStreamEvent) -> bool:
    return event.url.startswith("https://chatgpt.com/unauth-mweb/conversation/updates")


with sync_page() as page:
    policy = DevtoolsLogPolicy.from_any(categories=("fetch_stream",), fetch_stream_event_predicates=[predicate])
    user = DevtoolsService(page=page, output_folder="./usage/check", policy=policy)
    user.start()
    page.goto(address)
    prompt = page.locator("#mobile-composer-prompt")
    prompt.fill("炊飯器について教えてくださいー")
    page.locator("button[data-composer-submit]").click()
    page.wait_for_timeout(30_000)
    html = page.content()

    # print(clean_html(html))
