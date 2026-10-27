from typing import Literal

from selectolax.lexbor import LexborHTMLParser

HtmlSimplificationMode = Literal["light", "balanced", "aggressive"]


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

    parser = LexborHTMLParser(html)
    parser.strip_tags(["script", "style"])

    if mode == "aggressive":
        for node in parser.css("svg"):
            attrs = {name.lower(): value for name, value in node.attributes.items()}
            role_tokens = set((attrs.get("role") or "").lower().split())
            explicitly_hidden = (attrs.get("aria-hidden") or "").lower() == "true"
            presentational = bool(role_tokens.intersection({"none", "presentation"}))
            has_accessible_metadata = "role" in attrs or "title" in attrs or any(
                name.startswith("aria-") for name in attrs
            )
            has_text_content = bool(node.text(deep=True, strip=True))

            if explicitly_hidden or presentational or not (has_accessible_metadata or has_text_content):
                node.decompose()

    if mode != "light":
        for node in parser.css("*"):
            if "style" in node.attributes:
                del node.attrs["style"]

    return parser.html or ""


def clean_html(html: str) -> str:
    KEEP_ATTRS = {
        "id",
        "class",
        "name",
        "type",
        "role",
        "title",
        "href",
        "for",
        "value",
        "placeholder",
        "contenteditable",
        "tabindex",
        "alt",
        "checked",
        "selected",
        "disabled",
        "multiple",
        "readonly",
        "required",
        "src",
        "autocomplete",
        "min",
        "max",
        "step",
        "minlength",
        "maxlength",
        "pattern",
    }

    # data-* と aria-* はすべて残す
    KEEP_PREFIXES = ("data-", "aria-")

    tree = LexborHTMLParser(html)

    for node in tree.css("*"):
        attrs = node.attributes

        for attr in list(attrs.keys()):
            attr_lower = attr.lower()

            if attr_lower in KEEP_ATTRS or attr_lower.startswith(KEEP_PREFIXES):
                continue

            # selectolax の属性辞書から不要な属性を削除
            del attrs[attr]

    return str(tree.html)
