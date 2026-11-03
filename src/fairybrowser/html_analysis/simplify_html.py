from typing import Literal

from selectolax.lexbor import LexborNode

from .html_simplifier import (
    HTMLSimplifier,
    KeepRelevantAttributesRule,
    RemoveScriptAndStyleRule,
)

HtmlSimplificationMode = Literal["light", "balanced", "aggressive"]


class _RemoveInlineStylesRule:
    def predicate(self, node: LexborNode) -> bool:
        return "style" in node.attributes

    def simplify(self, node: LexborNode) -> None:
        del node.attrs["style"]


class _RemoveDecorativeSvgRule:
    def predicate(self, node: LexborNode) -> bool:
        if node.tag != "svg":
            return False

        attrs = {name.lower(): value for name, value in node.attributes.items()}
        role_tokens = set((attrs.get("role") or "").lower().split())
        explicitly_hidden = (attrs.get("aria-hidden") or "").lower() == "true"
        presentational = bool(role_tokens.intersection({"none", "presentation"}))
        has_accessible_metadata = "role" in attrs or "title" in attrs or any(
            name.startswith("aria-") for name in attrs
        )
        has_text_content = bool(node.text(deep=True, strip=True))
        return explicitly_hidden or presentational or not (has_accessible_metadata or has_text_content)

    def simplify(self, node: LexborNode) -> None:
        node.decompose()


def simplify_html_for_playwright(
    html: str,
    *,
    mode: HtmlSimplificationMode = "balanced",
) -> str:
    """Remove nonessential markup while preserving DOM content and useful attributes.

    ``light`` removes script and stylesheet elements. ``balanced`` also removes
    inline styles. ``aggressive`` additionally removes SVGs that have no
    accessible name or text and are not explicitly exposed as meaningful.
    """
    if mode not in ("light", "balanced", "aggressive"):
        raise ValueError(f"Unsupported HTML simplification mode: {mode!r}")

    rules = []
    if mode == "aggressive":
        rules.append(_RemoveDecorativeSvgRule())
    if mode != "light":
        rules.append(_RemoveInlineStylesRule())

    return HTMLSimplifier(
        rules=rules,
        default_rules=[RemoveScriptAndStyleRule()],
    ).simplify(html)


def clean_html(html: str) -> str:
    return HTMLSimplifier(
        rules=[KeepRelevantAttributesRule()],
        node_protection_rules=(),
        subtree_protection_rules=(),
        default_rules=(),
    ).simplify(html)
