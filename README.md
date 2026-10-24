# fairybrowser

**This is an individual practice project, not so refined.**

A small Python project that helps start and connect to Chromium-based browsers via Playwright's CDP (Chrome DevTools Protocol). It includes utilities for finding available TCP ports, monitoring browser processes, and convenience helpers for connecting to a running browser instance.


## Features

- Start Chromium with remote debugging enabled and a user profile directory.
- Find an available local port (with preferred candidates or a range).
- Save and load running browser execution state (name + pid) and check if the process is still alive.
- Helpers to obtain a Playwright `Browser` object connected over CDP.
- Example prompt files under `prompts/` and `.github/prompts/` for repository-scoped assistant usage.

## Repository layout (important files)

- `pyproject.toml` — project configuration
- `src/fairybrowser/` — main package
	- `runners.py` — start browser processes, connect, and helpers
	- `monitors.py` — save/load execution state and check pid/alive
	- `port_utils.py` — find/verify available TCP ports
	- `utils.py` — higher-level helpers (pages, windows)
	- `process_utils.py` — process / window utilities
- `tests/` — pytest tests (basic coverage for the utilities)
- `.vscode/` — recommended VS Code settings, extensions and debug config

## Quickstart (development)

Prerequisites

- Python 3.12 >=
- uv
- Optional: Playwright and browser binaries

Setup

```powershell
# from repository root
uv sync 
uv run python -m playwright install
```

Run tests

```powershell
pytest -q
```

Note: This project currently includes only a few small unit tests under `tests/`. 

## Usage

High-level helper functions live in `src/fairybrowser/runners.py`.

Example: start a Chromium instance and connect (programmatic)

```python
from fairybrowser import sync_page
from fairybrowser.models import BrowserInfo

info = BrowserInfo(name="my-fairy")
# This will start Chromium (if not already running) and return a Playwright Browser connected over CDP
with sync_page(info) as page:
    page.goto("https://example.com")
    print(page.title())
```

## Devtools: HTTPTransactionAnalyzer

The `devtools` helpers collect selected CDP network events and store them under a debug folder. By default, HTTP, EventSource, and WebSocket logs are enabled; fetch stream capture and console logging are disabled. Configure `DevtoolsUser` with a `DevtoolsLogPolicy` to change the captured categories. HTTP transactions are saved as JSON files; EventSource and WebSocket events are appended to separate JSON Lines files per request ID under `network/event_stream/` and `network/websocket/`, with sanitized, hashed filenames. Fetch response chunks are appended to `network/fetch_stream.jsonl`. Fetch capture observes textual and JSON-like responses by cloning the response body, leaving the page's response available to the application. `HTTPTransactionAnalyzer` reads the HTTP logs and converts each exchange to an `HTTPTransaction` containing an `HTTPRequest` and an optional `HTTPResponse`.

Typical usage:

```python
import json
from fairybrowser import sync_page
from fairybrowser.devtools.collectors import DevtoolsUser
from fairybrowser.devtools.analyzers import HTTPTransactionAnalyzer

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
```

Notes:

- Use `DevtoolsLogPolicy.from_any(policy_mode="all")` to enable every category, including fetch stream and console capture, then pass it as `DevtoolsUser(page, "./debug", policy=policy)`.
- Set `save_memory=True` to retain captured network logs in `collector.network_log`; call `.snapshot()` for an immutable tuple-based view. `output_folder` may also be supplied to write logs to disk, and is initialized (cleared) on collector construction.
- Import `NetworkLog` from `fairybrowser.devtools.models.network_log` and call `NetworkLog.load("./debug")` to load saved files together. It groups HTTP transactions, Server-Sent Events, and WebSocket connections while preserving fetch stream events.
- HTTP transaction, WebSocket connection, and Server-Sent Events predicates can filter which grouped logs are saved.
- `HTTPTransactionAnalyzer` accepts the path to the log folder (it will assert the folder exists).
- It automatically finds JSON files under the folder and under `network/` within the folder.
- `HTTPTransaction.request` contains the request method, URL, headers, and bytes body.
- `HTTPTransaction.response` is `None` when no response data was recorded; otherwise it contains the status, headers, and bytes body.
- `HTTPRequest.body_json` and `HTTPResponse.body_json` attempt to decode JSON bodies; if decoding fails they return the raw text.

I added unit tests for the analyzer in `tests/test_analyzers.py` which validate parsing and filtering by method/path.



## License

This repository includes a `LICENSE` file in the workspace root.
