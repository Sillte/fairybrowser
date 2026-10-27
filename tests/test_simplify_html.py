from typing import cast

import pytest

from fairybrowser.html_analysis.simplify_html import HtmlSimplificationMode, simplify_html_for_playwright


def test_light_mode_removes_script_and_stylesheet_elements_only():
    html = '<div style="color: red" data-custom="kept">Text<script>alert(1)</script><style>.x {}</style></div>'

    simplified = simplify_html_for_playwright(html, mode="light")

    assert "Text" in simplified
    assert "script" not in simplified
    assert "<style" not in simplified
    assert 'style="color: red"' in simplified
    assert 'data-custom="kept"' in simplified


def test_balanced_mode_removes_inline_styles_and_preserves_attributes():
    html = '<button class="submit" style="display: none" data-action="send" aria-label="Send" custom="value">Go</button>'

    simplified = simplify_html_for_playwright(html)

    assert 'class="submit"' in simplified
    assert 'data-action="send"' in simplified
    assert 'aria-label="Send"' in simplified
    assert 'custom="value"' in simplified
    assert "style=" not in simplified
    assert "Go" in simplified


def test_aggressive_mode_removes_only_decorative_svg():
    html = """
    <div>
      <svg class="decoration"><path d="M0 0"></path></svg>
      <svg role="img" aria-label="Profile"><circle></circle></svg>
      <svg><text>Chart label</text></svg>
      <svg>Brand mark<path d="M0 0"></path></svg>
      <iframe title="Embedded content"></iframe>
    </div>
    """

    simplified = simplify_html_for_playwright(html, mode="aggressive")

    assert "decoration" not in simplified
    assert 'aria-label="Profile"' in simplified
    assert "Chart label" in simplified
    assert "Brand mark" in simplified
    assert 'title="Embedded content"' in simplified


def test_unknown_mode_raises_value_error():
    with pytest.raises(ValueError, match="Unsupported HTML simplification mode"):
        simplify_html_for_playwright("<p>Text</p>", mode=cast(HtmlSimplificationMode, "unknown"))
