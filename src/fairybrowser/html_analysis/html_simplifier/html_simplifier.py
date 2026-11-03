from typing import Sequence

from selectolax.lexbor import LexborHTMLParser, LexborNode

from .models import (
    NodeProtectionRuleProtocol,
    SimplificationRuleProtocol,
    SubtreeProtectionRuleProtocol,
)
from .protection_rules import MainTagProtectionRule


class HTMLSimplifier:
    def __init__(
        self,
        rules: Sequence[SimplificationRuleProtocol] = (),
        *,
        node_protection_rules: Sequence[NodeProtectionRuleProtocol] | None = None,
        subtree_protection_rules: Sequence[SubtreeProtectionRuleProtocol] | None = None,
        default_rules: Sequence[SimplificationRuleProtocol] | None = None,
    ) -> None:
        if node_protection_rules is None:
            node_protection_rules = self._make_default_node_protection_rules()
        if subtree_protection_rules is None:
            subtree_protection_rules = self._make_default_subtree_protection_rules()
        if default_rules is None:
            default_rules = self._make_default_rules()

        self._rules = [*rules, *default_rules]
        self._node_protection_rules = node_protection_rules
        self._subtree_protection_rules = subtree_protection_rules

    @classmethod
    def _make_default_rules(cls) -> Sequence[SimplificationRuleProtocol]:
        return []

    @classmethod
    def _make_default_node_protection_rules(cls) -> Sequence[NodeProtectionRuleProtocol]:
        return [MainTagProtectionRule()]

    @classmethod
    def _make_default_subtree_protection_rules(cls) -> Sequence[SubtreeProtectionRuleProtocol]:
        return []

    def simplify(self, html: str) -> str:
        parser = LexborHTMLParser(html)
        if parser.root is None:
            return html
        self._traverse(parser.root)
        return str(parser.html)

    def _traverse(self, node: LexborNode) -> None:
        if node.is_element_node and any(rule.predicate(node) for rule in self._subtree_protection_rules):
            return

        child = node.first_child
        while child is not None:
            next_child = child.next
            if child.is_element_node:
                self._traverse(child)
            child = next_child

        if not node.is_element_node:
            return
        if any(rule.predicate(node) for rule in self._node_protection_rules):
            return

        for rule in self._rules:
            if rule.predicate(node):
                rule.simplify(node)
