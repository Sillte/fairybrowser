from __future__ import annotations

from typing import Sequence

from selectolax.lexbor import LexborHTMLParser

from fairybrowser.html_analysis.markdown_converter.converters import (
    BlockQuoteConverter,
    BoldConverter,
    HeadingConverter,
    HorizontalRuleConverter,
    ImageConverter,
    InlineCodeConverter,
    ItalicConverter,
    LineBreakConverter,
    LinkConverter,
    ListConverter,
    ParagraphConverter,
    PreformattedConverter,
    StrikethroughConverter,
    TextConverter,
)
from fairybrowser.html_analysis.markdown_converter.models import (
    InputContext,
    NodeConverterProtocol,
    NodeProcessorProtocol,
    OutputContext,
)

from .processor import Processor

__all__ = [
    "NodeConverterProtocol",
    "InputContext",
    "MarkdownConverter",
    "NodeProcessorProtocol",
    "OutputContext",
]


class MarkdownConverter:
    def __init__(
        self,
        converters: Sequence[NodeConverterProtocol] = tuple(),
        *,
        basic_converters: Sequence[NodeConverterProtocol] | None = None,
    ) -> None:
        self._converters = converters
        if basic_converters is None:
            basic_converters = self._make_default_basic_converters()
        self._basic_converters = basic_converters

    @classmethod
    def _make_default_basic_converters(cls) -> Sequence[NodeConverterProtocol]:
        return [
            HeadingConverter(),
            ParagraphConverter(),
            BoldConverter(),
            ItalicConverter(),
            StrikethroughConverter(),
            InlineCodeConverter(),
            LinkConverter(),
            ImageConverter(),
            ListConverter(),
            BlockQuoteConverter(),
            PreformattedConverter(),
            LineBreakConverter(),
            HorizontalRuleConverter(),
            TextConverter(),
        ]

    def convert(self, html: str) -> str:
        parser = LexborHTMLParser(html)
        converters = [*self._converters, *self._basic_converters]
        processor = Processor(converters)

        root = parser.root
        if root is None:
            raise ValueError("root is not found.")

        context = InputContext(current_node=root, node_processor=processor)
        output = processor.process(context)
        return output.markdown


if __name__ == "__main__":
    html = "<h1>Hello <em>world</em></h1><p>A <strong>basic</strong> example.</p>"
    print(MarkdownConverter().convert(html))
