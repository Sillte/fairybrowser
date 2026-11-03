from fairybrowser.html_analysis import (
    ConverterProtocol,
    HtmlSimplificationMode,
    HTMLSimplifier,
    InputContext,
    MarkdownConverter,
    NodeProcessorProtocol,
    NodeProtectionRuleProtocol,
    OutputContext,
    SimplificationRuleProtocol,
    SubtreeProtectionRuleProtocol,
    clean_html,
    simplify_html_for_playwright,
)


def test_html_analysis_exports_supported_api():
    assert "<p>hello</p>" in HTMLSimplifier().simplify("<p>hello</p>")
    assert MarkdownConverter().convert("<p>hello</p>").strip() == "hello"
    assert "<script>" not in simplify_html_for_playwright("<script>x</script>")
    assert "onclick" not in clean_html('<button onclick="x">go</button>')
    assert HtmlSimplificationMode is not None
    assert ConverterProtocol is not None
    assert InputContext is not None
    assert NodeProcessorProtocol is not None
    assert OutputContext is not None
    assert NodeProtectionRuleProtocol is not None
    assert SimplificationRuleProtocol is not None
    assert SubtreeProtectionRuleProtocol is not None
