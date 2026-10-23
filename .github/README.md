## GitHub metadata for this repository

This repository uses a small helpers layout for developer experience files.

- Prompt examples are placed in the top-level `prompts/` directory. They are not code, but handy examples to use when interacting with an assistant.
- If you want CI workflows (GitHub Actions) or issue/PR templates added here, tell me and I will add a sample `workflows/python-ci.yml` and templates.

Repository-scoped prompts (for Copilot / assistant discovery)
---------------------------------------------------------

To make repository-scoped prompt examples discoverable by tools that search under the `.github` folder (for example some Copilot features), this repo also contains a copy under `.github/prompts/`.

- Files available there:
	- `/.github/prompts/example_prompt.md` — long prompt example
	- `/.github/prompts/example_prompt.txt` — short prompt example

Notes and assumptions:
- Different Copilot or assistant integrations may look for prompts under different paths (for example `/.github/copilot/` or `/.copilot/`). If you need a different location (e.g. `.github/copilot/prompts/`), tell me and I will move or duplicate the files.
- You can reference these files in tooling or by path patterns like `/.github/prompts/**` when configuring repository-scoped prompts.

