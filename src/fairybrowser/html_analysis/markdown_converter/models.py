from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence

from selectolax.lexbor import LexborNode


class NodeProcessorProtocol(Protocol):
    def process(self, context: InputContext) -> OutputContext: ...

    def process_children(self, parent: LexborNode) -> OutputContext: ...


@dataclass(frozen=True)
class InputContext:
    current_node: LexborNode
    node_processor: "NodeProcessorProtocol"


@dataclass
class OutputContext:
    markdown: str
    end_node: LexborNode


class ConverterProtocol(Protocol):
    @property
    def tags(self) -> Sequence[str] | None: ...

    def predicate(self, context: InputContext) -> bool: ...

    def convert(
        self,
        context: InputContext,
    ) -> OutputContext: ...
