import json

from fairybrowser.devtools.analyzers import HTTPTransactionAnalyzer
from fairybrowser.devtools.collectors import DevtoolsUser

if __name__ == "__main__":
    from fairybrowser import sync_page

    with sync_page() as page:
        DevtoolsUser(page, "./debug").start()
        page.goto("about:blank")
        test_url = "https://httpbin.org/post"
        payload = {"foo": "bar", "num": 123}
        page.evaluate(f'''
            fetch("{test_url}", {{
                method: "POST",
                headers: {{ "Content-Type": "application/json" }},
                body: JSON.stringify({json.dumps(payload)})
            }});
        ''')
        page.wait_for_timeout(3000)
    transactions = HTTPTransactionAnalyzer("./debug").get_transactions()
    for transaction in transactions:
        request_data = transaction.request.body_json
        response_data = transaction.response.body_json if transaction.response else None
        print(request_data, response_data)
