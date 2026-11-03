from selectolax.lexbor import LexborNode


class RemoveScriptAndStyleRule:
    TARGET_TAGS = {"script", "style"}

    def predicate(self, node: LexborNode) -> bool:
        return node.tag in self.TARGET_TAGS

    def simplify(self, node: LexborNode) -> None:
        node.decompose()


class KeepRelevantAttributesRule:
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
    KEEP_PREFIXES = ("data-", "aria-")

    @classmethod
    def _is_relevant(cls, name: str) -> bool:
        name = name.lower()
        return name in cls.KEEP_ATTRS or name.startswith(cls.KEEP_PREFIXES)

    def predicate(self, node: LexborNode) -> bool:
        return any(not self._is_relevant(name) for name in node.attributes)

    def simplify(self, node: LexborNode) -> None:
        for name in list(node.attributes):
            if not self._is_relevant(name):
                del node.attrs[name]
