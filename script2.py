from bs4 import BeautifulSoup
import sys


# Playwright の要素特定・操作に役立つ属性
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
    "aria-label",
    "aria-labelledby",
    "aria-describedby",
    "aria-checked",
    "aria-selected",
    "aria-expanded",
    "aria-disabled",
    "aria-pressed",
    "data-testid",
    "data-test",
    "data-cy",
    "contenteditable",
    "tabindex",
    "alt",
    "checked",
    "selected",
    "disabled",
    "multiple",
    "readonly",
    "required",
}

# data-* / aria-* は原則すべて残す
KEEP_PREFIXES = ("data-", "aria-")


def clean_html(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup.find_all(True):
        attrs_to_remove = []

        for attr in tag.attrs:
            attr_lower = attr.lower()

            if attr_lower in KEEP_ATTRS or attr_lower.startswith(KEEP_PREFIXES):
                continue

            attrs_to_remove.append(attr)

        for attr in attrs_to_remove:
            del tag.attrs[attr]

    return str(soup)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python clean_html.py input.html")
        sys.exit(1)

    input_file = sys.argv[1]

    with open(input_file, "r", encoding="utf-8") as f:
        html = f.read()

    result = clean_html(html)

    output_file = input_file.rsplit(".", 1)[0] + ".clean.html"

    with open(output_file, "w", encoding="utf-8") as f:
        f.write(result)

    print(f"保存しました: {output_file}")
