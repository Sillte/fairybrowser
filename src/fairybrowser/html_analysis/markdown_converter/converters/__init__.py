import re
from typing import Sequence

from fairybrowser.html_analysis.markdown_converter.models import InputContext, OutputContext


def _children_markdown(context: InputContext) -> str:
    node = context.current_node
    if node.first_child is None:
        return ""
    return context.node_processor.process_children(node).markdown


class HeadingConverter:
    @property
    def tags(self) -> Sequence[str]:
        return ("h1", "h2", "h3", "h4", "h5", "h6")

    def predicate(self, context: InputContext) -> bool:
        return context.current_node.tag in self.tags

    def convert(self, context: InputContext) -> OutputContext:
        node = context.current_node
        tag = node.tag or "h1"
        level = int(tag[1])
        content = _children_markdown(context).strip()
        return OutputContext(markdown=f"{'#' * level} {content}\n\n", end_node=node)


class ParagraphConverter:
    @property
    def tags(self) -> Sequence[str]:
        return ("p",)

    def predicate(self, context: InputContext) -> bool:
        return context.current_node.tag == "p"

    def convert(self, context: InputContext) -> OutputContext:
        node = context.current_node
        return OutputContext(markdown=f"{_children_markdown(context)}\n\n", end_node=node)


class BoldConverter:
    @property
    def tags(self) -> Sequence[str]:
        return ("strong", "b")

    def predicate(self, context: InputContext) -> bool:
        return context.current_node.tag in self.tags

    def convert(self, context: InputContext) -> OutputContext:
        node = context.current_node
        return OutputContext(markdown=f"**{_children_markdown(context)}**", end_node=node)


class ItalicConverter:
    @property
    def tags(self) -> Sequence[str]:
        return ("em", "i")

    def predicate(self, context: InputContext) -> bool:
        return context.current_node.tag in self.tags

    def convert(self, context: InputContext) -> OutputContext:
        node = context.current_node
        return OutputContext(markdown=f"*{_children_markdown(context)}*", end_node=node)


class StrikethroughConverter:
    @property
    def tags(self) -> Sequence[str]:
        return ("del", "s", "strike")

    def predicate(self, context: InputContext) -> bool:
        return context.current_node.tag in self.tags

    def convert(self, context: InputContext) -> OutputContext:
        node = context.current_node
        return OutputContext(markdown=f"~~{_children_markdown(context)}~~", end_node=node)


class InlineCodeConverter:
    @property
    def tags(self) -> Sequence[str]:
        return ("code",)

    def predicate(self, context: InputContext) -> bool:
        return context.current_node.tag == "code"

    def convert(self, context: InputContext) -> OutputContext:
        node = context.current_node
        content = _children_markdown(context)
        longest_backtick_run = max((len(run) for run in re.findall(r"`+", content)), default=0)
        delimiter = "`" * (longest_backtick_run + 1)
        padding = " " if content.startswith("`") or content.endswith("`") else ""
        return OutputContext(markdown=f"{delimiter}{padding}{content}{padding}{delimiter}", end_node=node)


class LinkConverter:
    @property
    def tags(self) -> Sequence[str]:
        return ("a",)

    def predicate(self, context: InputContext) -> bool:
        return context.current_node.tag == "a"

    def convert(self, context: InputContext) -> OutputContext:
        node = context.current_node
        label = _children_markdown(context)
        href = node.attributes.get("href")
        if not href:
            markdown = label
        else:
            markdown = f"[{label}]({href.replace(' ', '%20')})"
        return OutputContext(markdown=markdown, end_node=node)


class ImageConverter:
    @property
    def tags(self) -> Sequence[str]:
        return ("img",)

    def predicate(self, context: InputContext) -> bool:
        return context.current_node.tag == "img"

    def convert(self, context: InputContext) -> OutputContext:
        node = context.current_node
        src = node.attributes.get("src") or ""
        alt = node.attributes.get("alt") or ""
        markdown = f"![{alt}]({src.replace(' ', '%20')})" if src else alt
        return OutputContext(markdown=markdown, end_node=node)


class ListConverter:
    @property
    def tags(self) -> Sequence[str]:
        return ("ul", "ol")

    def predicate(self, context: InputContext) -> bool:
        return context.current_node.tag in self.tags

    def convert(self, context: InputContext) -> OutputContext:
        node = context.current_node
        ordered = node.tag == "ol"
        try:
            number = int(node.attributes.get("start") or "1")
        except ValueError:
            number = 1

        lines: list[str] = []
        child = node.first_child
        while child is not None:
            if child.tag == "li":
                content_parts: list[str] = []
                item_child = child.first_child
                while item_child is not None:
                    output = context.node_processor.process(
                        InputContext(
                            current_node=item_child,
                            node_processor=context.node_processor,
                        )
                    )
                    if item_child.tag in ("ul", "ol") and content_parts and not content_parts[-1].endswith("\n"):
                        content_parts.append("\n")
                    content_parts.append(output.markdown)
                    item_child = output.end_node.next

                content = "".join(content_parts).strip("\n")
                content_lines = content.splitlines() or [""]
                marker = f"{number}." if ordered else "-"
                indentation = " " * (len(marker) + 1)
                lines.append(f"{marker} {content_lines[0]}".rstrip())
                lines.extend(
                    f"{indentation}{line}" if line else ""
                    for line in content_lines[1:]
                )
                if ordered:
                    number += 1
            child = child.next

        markdown = "\n".join(lines)
        if markdown:
            markdown += "\n\n"
        return OutputContext(markdown=markdown, end_node=node)


class BlockQuoteConverter:
    @property
    def tags(self) -> Sequence[str]:
        return ("blockquote",)

    def predicate(self, context: InputContext) -> bool:
        return context.current_node.tag == "blockquote"

    def convert(self, context: InputContext) -> OutputContext:
        node = context.current_node
        content = _children_markdown(context).strip("\n")
        quoted_lines = [f"> {line}" if line else ">" for line in content.splitlines()]
        markdown = "\n".join(quoted_lines)
        if markdown:
            markdown += "\n\n"
        return OutputContext(markdown=markdown, end_node=node)


class PreformattedConverter:
    @property
    def tags(self) -> Sequence[str]:
        return ("pre",)

    def predicate(self, context: InputContext) -> bool:
        return context.current_node.tag == "pre"

    def convert(self, context: InputContext) -> OutputContext:
        node = context.current_node
        content = node.text(deep=True).strip("\n")
        longest_backtick_run = max((len(run) for run in re.findall(r"`+", content)), default=0)
        fence = "`" * max(3, longest_backtick_run + 1)
        markdown = f"{fence}\n{content}\n{fence}\n\n"
        return OutputContext(markdown=markdown, end_node=node)


class LineBreakConverter:
    @property
    def tags(self) -> Sequence[str]:
        return ("br",)

    def predicate(self, context: InputContext) -> bool:
        return context.current_node.tag == "br"

    def convert(self, context: InputContext) -> OutputContext:
        node = context.current_node
        return OutputContext(markdown="  \n", end_node=node)


class HorizontalRuleConverter:
    @property
    def tags(self) -> Sequence[str]:
        return ("hr",)

    def predicate(self, context: InputContext) -> bool:
        return context.current_node.tag == "hr"

    def convert(self, context: InputContext) -> OutputContext:
        node = context.current_node
        return OutputContext(markdown="\n---\n\n", end_node=node)


class TextConverter:
    @property
    def tags(self) -> None:
        return None

    def predicate(self, context: InputContext) -> bool:
        return context.current_node.is_text_node

    def convert(self, context: InputContext) -> OutputContext:
        node = context.current_node
        return OutputContext(markdown=node.text(), end_node=node)
