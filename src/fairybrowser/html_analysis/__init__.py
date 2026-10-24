import sys
from pathlib import Path

from selectolax.lexbor import LexborHTMLParser

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


def clean_html(html: str) -> str:
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
