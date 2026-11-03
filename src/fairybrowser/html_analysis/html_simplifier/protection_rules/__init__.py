from selectolax.lexbor import LexborNode


class MainTagProtectionRule:
    def predicate(self, node: LexborNode) -> bool:
        return node.tag in ("html", "body", "head", "")
