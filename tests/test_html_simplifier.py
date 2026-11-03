from selectolax.lexbor import LexborNode

from fairybrowser.html_analysis.html_simplifier import HTMLSimplifier, RemoveScriptAndStyleRule


class _RemoveDivRule:
    def predicate(self, node: LexborNode) -> bool:
        return node.tag == "div"

    def simplify(self, node: LexborNode) -> None:
        node.decompose()


class _RemoveHeadRule:
    def predicate(self, node: LexborNode) -> bool:
        return node.tag == "head"

    def simplify(self, node: LexborNode) -> None:
        node.decompose()


class _ProtectDiv:
    def predicate(self, node: LexborNode) -> bool:
        return node.tag == "div"


class _SimplifierWithDefaultRule(HTMLSimplifier):
    @classmethod
    def _make_default_rules(cls):
        return [RemoveScriptAndStyleRule()]


def test_node_protection_skips_node_but_traverses_children():
    simplifier = HTMLSimplifier(
        rules=[_RemoveDivRule()],
        node_protection_rules=[_ProtectDiv()],
        default_rules=[RemoveScriptAndStyleRule()],
    )

    simplified = simplifier.simplify("<div><script>hidden()</script>kept</div>")

    assert "<div>" in simplified
    assert "script" not in simplified
    assert "kept" in simplified


def test_subtree_protection_skips_matching_node_and_descendants():
    simplifier = HTMLSimplifier(
        default_rules=[RemoveScriptAndStyleRule()],
        subtree_protection_rules=[_ProtectDiv()],
    )

    simplified = simplifier.simplify(
        "<div><script>protected()</script></div><script>removed()</script>"
    )

    assert "protected()" in simplified
    assert "removed()" not in simplified


def test_none_uses_default_rules_and_empty_sequence_disables_them():
    with_defaults = _SimplifierWithDefaultRule()
    without_defaults = _SimplifierWithDefaultRule(default_rules=())

    assert "script" not in with_defaults.simplify("<script>x</script>")
    assert "<script>" in without_defaults.simplify("<script>x</script>")


def test_empty_node_protection_sequence_disables_default_protection():
    defaulted = HTMLSimplifier(rules=[_RemoveHeadRule()], default_rules=())
    explicitly_unprotected = HTMLSimplifier(
        rules=[_RemoveHeadRule()],
        node_protection_rules=(),
        default_rules=(),
    )

    assert "<head>" in defaulted.simplify("<head>protected</head>")
    assert "<head>" not in explicitly_unprotected.simplify("<head>removed</head>")


def test_empty_subtree_protection_sequence_disables_default_protection():
    class _SubtreeProtectingSimplifier(HTMLSimplifier):
        @classmethod
        def _make_default_subtree_protection_rules(cls):
            return [_ProtectDiv()]

    defaulted = _SubtreeProtectingSimplifier(
        default_rules=[RemoveScriptAndStyleRule()],
        node_protection_rules=(),
    )
    explicitly_unprotected = _SubtreeProtectingSimplifier(
        default_rules=[RemoveScriptAndStyleRule()],
        node_protection_rules=(),
        subtree_protection_rules=(),
    )

    assert "<script>" in defaulted.simplify("<div><script>x</script></div>")
    assert "script" not in explicitly_unprotected.simplify("<div><script>x</script></div>")
