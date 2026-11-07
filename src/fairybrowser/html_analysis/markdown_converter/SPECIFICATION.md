# Markdown Converter Specification

## Purpose and public API

`MarkdownConverter` converts an HTML string into Markdown using Selectolax's Lexbor parser. The supported imports are:

```python
from fairybrowser import MarkdownConverter
from fairybrowser.html_analysis import MarkdownConverter
```

Applications that implement custom converters can import `NodeConverterProtocol`, `InputContext`, `NodeProcessorProtocol`, and `OutputContext` from either `fairybrowser` or `fairybrowser.html_analysis`. `Processor` and built-in converter implementations are internal.

If the parser has no root node, conversion raises `ValueError`.

## Converter pipeline

- `Processor` owns DOM traversal and converter selection; converters own Markdown generation.
- A converter implements `NodeConverterProtocol`:
  - `tags` returns tag names to match. A non-empty sequence restricts the converter to those tags; `None` or an empty sequence makes it eligible for every tag.
  - `predicate(context)` returns whether the converter handles the current node. It is evaluated only for eligible converters.
  - `convert(context)` returns an `OutputContext` containing the Markdown and the last node consumed.
- The processor checks converters registered for the current node's tag, then converters without a tag restriction. For each group, converters are tried in the order supplied; the first whose predicate is true is used.
- `OutputContext.end_node` must be the current node when consuming only that node. If a converter consumes additional consecutive siblings, it must be the last sibling it consumed, so traversal can resume at its next sibling. Do not return a descendant or an unrelated node.
- User-supplied converters run before built-ins and can override built-in behavior for the same tag.
- `basic_converters=None` uses the built-in set. An explicitly empty sequence disables built-ins.
- If no converter handles a node, its children are processed recursively. Text nodes are emitted by the built-in `TextConverter`; unknown element tags are omitted while their contents are retained.
- A converter returns `OutputContext(markdown, end_node)`. `end_node` identifies the last consumed node so traversal can resume at its next sibling. Return the current node when consuming only that node.

## Built-in conversions

| HTML | Markdown output |
| --- | --- |
| `h1`–`h6` | `#` through `######`, followed by a space and the heading content; blank-line separated |
| `p` | Child content followed by a blank line |
| `strong`, `b` | `**bold**` |
| `em`, `i` | `*italic*` |
| `del`, `s`, `strike` | `~~strikethrough~~` |
| `code` | Inline code with a backtick delimiter long enough not to collide with contained backtick runs |
| `pre` | Fenced code block; the fence is longer than any backtick run in the content |
| `a` | `[label](href)` when `href` is present; otherwise the label only. The `href` value is emitted without normalization, scheme validation, or escaping, except that spaces are replaced with `%20` |
| `img` | `![alt](src)` when `src` is present; otherwise the `alt` text |
| `ul`, `ol`, `li` | `-` unordered markers or numbered ordered markers; `ol[start]` sets the first number and nested lists are indented |
| `blockquote` | Each content line is prefixed with `>` |
| `br` | Markdown hard line break (two spaces and a newline) |
| `hr` | `---` horizontal rule with surrounding line breaks |

Text-node content is otherwise retained as provided by the parser. Block converters add their own newline spacing as described above.

## Extension and limitations

Implement `NodeConverterProtocol` and pass instances through `converters` to support additional elements. Pass `basic_converters` to replace the built-in set; use an empty sequence to disable it entirely.

This is a basic HTML-to-Markdown conversion, not a complete HTML or CommonMark implementation. Tables and many semantic or interactive elements do not have dedicated conversions; unhandled elements are traversed and their child content is retained. Escaping for attributes other than the `href` behavior described above, link titles, reversed/valued ordered-list items, and detailed whitespace normalization are not specified.
