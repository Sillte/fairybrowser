# Design Policy

## Public Python API

- The supported package-level APIs of `fairybrowser`, `fairybrowser.devtools`, and `fairybrowser.html_analysis` are declared explicitly in `__all__` in their respective `__init__.py` files.
- Consumers should import supported types from those package APIs, not implementation modules. Internal module paths may change without preserving compatibility.
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
- Keep detailed contracts in `SPECIFICATION.md` files beside their owning packages; use the root `SPECIFICATION.md` as an index with links rather than duplicating package details.

## HTML-to-Markdown Conversion

- Keep DOM traversal and converter selection in `Processor`; keep Markdown syntax generation in `ConverterProtocol` implementations.
- Use tag declarations to narrow converter candidates, then use `predicate` to determine whether a converter applies. Converters without declared tags are considered for every node.
- Evaluate user-supplied converters before built-in converters so custom behavior can override a built-in conversion for the same tag.
- Treat `basic_converters=None` as “use the built-in set”; an explicitly empty sequence disables built-ins.
- Preserve the contents of unknown HTML elements by recursively processing their children. Add support for new HTML constructs through converters rather than embedding tag-specific output logic in the traversal engine.
- Expose the supported converter API through both `fairybrowser.__all__` and `fairybrowser.html_analysis.__all__`; keep traversal classes and built-in converter implementations internal.
- Keep the supported elements, output conventions, and known limitations documented in the package-local `SPECIFICATION.md`, linked from the root specification, with tests for observable conversion behavior.

## HTML Simplification

- Expose `HTMLSimplifier`, its extension protocols, and the supported HTML simplification helpers through `fairybrowser.html_analysis.__all__`; keep rule implementations and traversal details internal unless explicitly supported.
- Keep HTML parsing and traversal in `HTMLSimplifier`; each `SimplificationRuleProtocol` owns one local DOM transformation.
- Apply caller-supplied `rules` before `default_rules`, preserving the declared order within each sequence. `default_rules=None` selects `_make_default_rules()`; an explicitly empty sequence disables defaults.
- `NodeProtectionRuleProtocol` protects only the matching node from simplification; its children are still traversed. `SubtreeProtectionRuleProtocol` protects the matching node and skips traversal of its descendants.
- `node_protection_rules=None` and `subtree_protection_rules=None` select their respective defaults. An explicitly empty sequence disables protection of that kind.
- Keep content-preserving simplification separate from attribute filtering. Attribute filtering may use the simplifier with protection disabled so structural elements are treated consistently with all other elements.
- Document observable modes and attribute policies in the package-local `SPECIFICATION.md`, linked from the root specification; test rule order, protection scope, default selection, and preservation of content and attributes.
