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

## Devtools

The `devtools` helpers collect selected CDP network events and store them under a debug folder. By default, HTTP, EventSource, and Websocket logs are enabled; fetch stream capture and console logging are disabled. Configure `DevtoolsService` with a `DevtoolsLogPolicy` to change the captured categories. HTTP transactions are saved as JSON files; EventSource and Websocket events are appended to separate JSON Lines files per request ID under `network/event_stream/` and `network/websocket/`, with sanitized, hashed filenames. Fetch response chunks are appended to `network/fetch_stream.jsonl`. Fetch capture observes textual and JSON-like responses by cloning the response body, leaving the page's response available to the application. `NetworkLog.load()` loads the saved exchanges and events as typed models.

`DevtoolsService` also exposes typed events for live notifications. Subscribe before starting the service, and terminate it when finished. Use `fetch_stream_event_predicates` to filter Fetch events; multiple predicates use any-match semantics:

```python
policy = DevtoolsLogPolicy.from_any(
    policy_mode="all",
    fetch_stream_event_predicates=lambda event: event.event_type == "chunk",
)
devtools = DevtoolsService(page, "./debug", policy=policy)
devtools.on_fetch_stream_event.subscribe(
    lambda event: print("Fetch chunk:", event.url, event.text)
)
devtools.on_server_sent_event.subscribe(
    lambda event: print("Server-Sent Event:", event.data)
)
devtools.on_http_transaction.subscribe(
    lambda transaction: print("HTTP:", transaction.request.method, transaction.request.url)
)
devtools.start()
try:
    page.goto("https://example.com")
finally:
    devtools.terminate()
```

Typical usage:

```python
from fairybrowser import sync_page
from fairybrowser.devtools import DevtoolsService, NetworkLog

with sync_page() as page:
    service = DevtoolsService(page, "./debug")
    service.start()
    try:
        page.goto("https://example.com")
    finally:
        service.terminate()

network_log = NetworkLog.load("./debug")
transactions = network_log.get_http_transactions(method="POST", path="/")
for transaction in transactions:
    request_data = transaction.request.body_json
    response_data = transaction.response.body_json if transaction.response else None
    print(request_data, response_data)
```

Notes:

- Use `DevtoolsLogPolicy.from_any(policy_mode="all")` to enable every category, including fetch stream and console capture, then pass it as `DevtoolsService(page, "./debug", policy=policy)`.
- Set `save_memory=True` to retain captured network logs in `service.network_log`; call `.snapshot()` for an immutable tuple-based view. `output_folder` may also be supplied to write logs to disk, and is initialized (cleared) on service construction.
- Import `NetworkLog` from `fairybrowser.devtools` and call `NetworkLog.load("./debug")` to load saved files together. It groups HTTP transactions, Server-Sent Events, and Websocket connections while preserving fetch stream events.
- HTTP transaction, Websocket connection, and Server-Sent Events predicates can filter which grouped logs are saved.
- Use `network_log.get_http_transactions(method="POST", path="/api")` to filter loaded HTTP transactions by case-insensitive method and URL substring.
- Import `DevtoolsService`, `DevtoolsLogPolicy`, `NetworkLog`, and the public event/model types from `fairybrowser.devtools`; import `sync_browser`, `sync_page`, `BrowserInfo`, `MousePlayer`, and `MouseRecorder` from `fairybrowser`. `DevtoolsService` is also available from the top-level package.
- `HTTPTransaction.request` contains the request method, URL, headers, and bytes body.
- `HTTPTransaction.response` is `None` when no response data was recorded; otherwise it contains the status, headers, and bytes body.
- `HTTPRequest.body_json` and `HTTPResponse.body_json` attempt to decode JSON bodies; if decoding fails they return the raw text.



## License

This repository includes a `LICENSE` file in the workspace root.
