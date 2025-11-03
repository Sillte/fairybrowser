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

- Python 3.11 >=
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
from fairybrowser import runners
from fairybrowser.models import BrowserInfo

info = BrowserInfo(name="my-fairy", port=None)
# This will start Chromium (if not already running) and return a Playwright Browser connected over CDP
with runners.sync_browser(info) as browser:
		page = browser.new_page()
		page.goto("https://example.com")
		print(page.title())
```

If you prefer a singleton-style Playwright instance (module-scoped) or different lifecycle handling, see `runners.sync_browser` implementation and consider swapping the approach to a long-lived Playwright instance.

## VS Code configuration

This repository contains `.vscode/settings.json`, `.vscode/extensions.json`, and `.vscode/launch.json`. These provide recommended extensions (Python, Pylance, Ruff, Black), format-on-save, and a debug configuration for running pytest or the current Python file.

## Prompts for Copilot / Assistant

Prompt examples live in  `.github/prompts/` so they can be discovered by tools that scan repository-scoped metadata. Use the `/.github/prompts/**` glob when referencing them in tooling.

## Devtools: SimpleRequestAnalyzer

The `devtools` helpers collect raw CDP network events and store them as JSON files under a debug folder. `SimpleRequestAnalyzer` reads those logs and converts them into a convenient `SimpleRequest` model which exposes parsed `payload` and `response_json` properties.

Typical usage:

```python
import json
from fairybrowser import  sync_page
from fairybrowser.devtools.collectors import DevtoolsUser
from fairybrowser.devtools.analyzers import SimpleRequestAnalyzer

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
```

Notes:

- `SimpleRequestAnalyzer` accepts the path to the log folder (it will assert the folder exists).
- It automatically finds JSON files under the folder and under `network/` within the folder.
- `SimpleRequest.payload` and `SimpleRequest.response_json` attempt to decode JSON bodies; if decoding fails they return the raw text.

I added unit tests for the analyzer in `tests/test_analyzers.py` which validate parsing and filtering by method/path.

## Development notes and suggestions

- `port_utils.find_available_port` returns a free port but there is an inherent race: another process could bind the port after it is found. Acquire the port quickly after checking or let the OS assign an ephemeral port by binding to `0`.
- `monitors.is_pid_alive` uses `psutil.pid_exists` for portability. On Windows it falls back to a permissive approach if permissions prevent checking.
- `runners._run_chromium` currently starts Chromium via `subprocess.Popen` and saves the PID using `ExecutionInfo`. Consider managing process groups and stdout/stderr redirection for production usage.

## CI (suggestion)

I can add a GitHub Actions workflow to run tests and linting on push/PR. Suggested path: `.github/workflows/python-ci.yml` with steps to set up Python, install deps, run `pytest`, and optionally run `ruff`.


## License

This repository includes a `LICENSE` file in the workspace root.

