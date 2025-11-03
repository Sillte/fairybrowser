from fairybrowser.devtools.collectors import DevtoolsUser
from fairybrowser.devtools.analyzers import SimpleRequestAnalyzer


if __name__ == "__main__":
    from fairybrowser import  sync_page
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
    requests = SimpleRequestAnalyzer("./debug").get_simple_requests()
    for request in requests:
        print(request.payload, request.response_json)

