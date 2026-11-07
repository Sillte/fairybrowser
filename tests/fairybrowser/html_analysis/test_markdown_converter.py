from typing import Sequence

from fairybrowser import InputContext, MarkdownConverter, NodeConverterProtocol, OutputContext


def test_converts_headings_paragraphs_and_inline_emphasis():
    html = "<h1>Title</h1><h2>Subtitle</h2><p><em>italic</em> <i>also italic</i> <strong>bold</strong> <del>removed</del></p>"

    markdown = MarkdownConverter().convert(html)

    assert markdown == "# Title\n\n## Subtitle\n\n*italic* *also italic* **bold** ~~removed~~\n\n"


def test_converts_links_images_inline_code_and_line_breaks():
    html = (
        '<p><a href="https://example.com/a b">link</a> <code>value</code><br><img src="/image.png" alt="diagram"></p>'
    )

    markdown = MarkdownConverter().convert(html)

    assert markdown == "[link](https://example.com/a%20b) `value`  \n![diagram](/image.png)\n\n"


def test_converts_nested_lists_and_blockquotes():
    html = (
        "<ol start='3'><li>first<ul><li>nested</li></ul></li><li>second</li></ol><blockquote><p>quoted</p></blockquote>"
    )

    markdown = MarkdownConverter().convert(html)

    assert markdown == "3. first\n   - nested\n4. second\n\n> quoted\n\n"


def test_converts_preformatted_code_and_horizontal_rules():
    html = "<pre><code>print('hello')\n</code></pre><hr>"

    markdown = MarkdownConverter().convert(html)

    assert markdown == "```\nprint('hello')\n```\n\n\n---\n\n"


def test_empty_basic_converters_are_respected():
    markdown = MarkdownConverter(basic_converters=[]).convert("<p>plain text</p>")

    assert markdown == ""


class CustomParagraphConverter:
    @property
    def tags(self) -> Sequence[str]:
        return ("p",)

    def predicate(self, context: InputContext) -> bool:
        return context.current_node.tag == "p"

    def convert(self, context: InputContext) -> OutputContext:
        return OutputContext(markdown="custom", end_node=context.current_node)


def test_custom_converter_takes_precedence_over_basic_converter():
    converter: NodeConverterProtocol = CustomParagraphConverter()
    markdown = MarkdownConverter(converters=[converter]).convert("<p>text</p>")

    assert markdown == "custom"
