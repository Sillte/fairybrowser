from fairybrowser import sync_page
from fairybrowser.devtools import DevtoolsUser
from fairybrowser.html_analysis import clean_html

address = "https://chatgpt.com/"

with sync_page() as page:
    user = DevtoolsUser(page=page, output_folder="./usage/check")
    user.start()
    page.goto(address)
    prompt = page.locator("#mobile-composer-prompt")
    prompt.fill("汝は人狼なりやのゲームについて教えてくださいー")
    page.locator("button[data-composer-submit]").click()
    page.wait_for_timeout(10_000)
    html = page.content()
    # print(clean_html(html))
