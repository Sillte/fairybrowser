# Design Policy

## Public Python API

- The supported package-level APIs of `fairybrowser` and `fairybrowser.devtools` are declared explicitly in `__all__` in their respective `__init__.py` files.
- Consumers should import supported types from `fairybrowser` or `fairybrowser.devtools`, not implementation modules. Internal module paths may change without preserving compatibility.
- Public names should describe their responsibility. Use `DevtoolsService` for the page-bound DevTools lifecycle; avoid names that imply a person or user.
- Add a separate abstraction only when it owns behavior or a distinct responsibility. Do not keep a wrapper that only forwards loading and filtering already owned by a domain object.

## DevTools Responsibilities

- `DevtoolsService` attaches to a Playwright page, captures configured events, and publishes live notifications.
- `NetworkLog` represents collected network data, loads persisted logs, and provides queries over those logs. It does not manage browser capture.
- Event and transaction models represent captured data; they do not depend on the service that produces them.
- `NetworkLogSnapshot` is the immutable view for consumers that need a stable snapshot of an in-memory log.

## Mouse Automation

- Mouse recording and playback live in the `fairybrowser.mouse` package; the name describes the functionality rather than the operating system.
- Mouse automation is currently Windows-only. Treat cross-platform support as a separate design change rather than implying it from the package name.

## API Evolution

- Preserve observable behavior when reorganizing internals unless a public API decision explicitly changes it.
- When replacing a public abstraction, move its useful behavior to the type that owns that responsibility and document the replacement.
- Keep the documented public API and package exports in sync.
