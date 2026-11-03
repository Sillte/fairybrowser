# HTML Simplifier Specification

## Purpose and public API

`HTMLSimplifier` applies DOM simplification rules to an HTML string. The supported package imports are:

```python
from fairybrowser.html_analysis import HTMLSimplifier
from fairybrowser.html_analysis import (
    NodeProtectionRuleProtocol,
    SimplificationRuleProtocol,
    SubtreeProtectionRuleProtocol,
)
```

The higher-level helpers `simplify_html_for_playwright`, `clean_html`, and `HtmlSimplificationMode` are also available from `fairybrowser.html_analysis`.

A simplification rule implements `predicate(node)` and `simplify(node)`. A protection rule implements `predicate(node)` to determine which node or subtree is protected.

## Rule and protection behavior

- Rules supplied through `rules` run before `default_rules`, preserving sequence order. Every matching rule is applied.
- `default_rules=None` uses `_make_default_rules()`; an explicitly empty sequence disables defaults.
- `node_protection_rules=None` and `subtree_protection_rules=None` use their respective defaults. An explicitly empty sequence disables that protection type.
- Node protection prevents simplification of the matching node but still traverses its children. Subtree protection prevents simplification of the matching node and skips traversal of its descendants.
- Subtree protection is checked before child traversal. Node protection is checked after child traversal.
- By default, `html`, `head`, and `body` nodes are protected from simplification, while their descendants remain eligible for rules.

## HTML simplification helpers

`simplify_html_for_playwright(html, mode=...)` preserves text and attributes unless a selected rule removes them. The default mode is `balanced`.

| Mode | Behavior |
| --- | --- |
| `light` | Removes `script` and `style` elements and their contents. |
| `balanced` | Also removes inline `style` attributes. |
| `aggressive` | Also removes SVG elements that are explicitly hidden or presentational, or have neither accessible metadata (`role`, `title`, or any `aria-*` attribute) nor text content. |

Unknown mode values raise `ValueError`. `noscript` elements are retained.

`clean_html(html)` filters attributes on every element while retaining text and element contents. It keeps the attributes `id`, `class`, `name`, `type`, `role`, `title`, `href`, `for`, `value`, `placeholder`, `contenteditable`, `tabindex`, `alt`, `checked`, `selected`, `disabled`, `multiple`, `readonly`, `required`, `src`, `autocomplete`, `min`, `max`, `step`, `minlength`, `maxlength`, and `pattern`, as well as all `data-*` and `aria-*` attributes. Other attributes, including inline `style`, are removed. It does not remove `script` or `style` elements.

`clean_html` uses the rule engine with default rules and both protection types disabled so attributes on structural elements are filtered consistently with other elements.
