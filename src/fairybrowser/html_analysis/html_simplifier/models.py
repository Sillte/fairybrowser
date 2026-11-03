from typing import Protocol

from selectolax.lexbor import LexborNode


class SimplificationRuleProtocol(Protocol):
    def predicate(self, node: LexborNode) -> bool: ...

    def simplify(self, node: LexborNode) -> None: ...


class NodeProtectionRuleProtocol(Protocol):
    def predicate(self, node: LexborNode) -> bool: ...


class SubtreeProtectionRuleProtocol(Protocol):
    def predicate(self, node: LexborNode) -> bool: ...
