from typing import Sequence

from selectolax.lexbor import LexborNode

from fairybrowser.html_analysis.markdown_converter.models import ConverterProtocol, InputContext, OutputContext


class Processor:
    def __init__(self, converters: Sequence[ConverterProtocol]):
        self.converters = converters

        self._tagged_converters: dict[str, list[ConverterProtocol]] = {}
        self._unbounded_converters: list[ConverterProtocol] = []

        for converter in converters:
            tags = converter.tags

            if not tags:
                self._unbounded_converters.append(converter)
                continue

            for tag in tags:
                self._tagged_converters.setdefault(tag, []).append(converter)

    def process(self, context: InputContext) -> OutputContext:
        """
        This function `process`es the current node.

        Returns:
            OutputContext:
                markdown: the markdown document of the direct children.
                end_node: the last_child of the parent.
        """
        node = context.current_node

        converter = self._select_converter(context)

        if converter is not None:
            return converter.convert(context)

        if node.first_child is None:
            return OutputContext(markdown="", end_node=node)
        else:
            children_output = self.process_children(node)
            return OutputContext(
                markdown=children_output.markdown,
                end_node=node,
            )

    def process_children(self, parent: LexborNode) -> OutputContext:
        """This function `processes` the direct children of `parent`.

        Returns:
            OutputContext:
                markdown: the markdown document of the direct children.
                end_node: the last_child of the parent.
        """
        if parent.first_child is None:
            raise ValueError(f"Childrent is not found for {parent=}")
        child: LexborNode | None = parent.first_child
        markdown_parts = []

        while child is not None:
            output = self.process(
                InputContext(
                    current_node=child,
                    node_processor=self,
                )
            )
            markdown_parts.append(output.markdown)
            end_node = output.end_node
            child = output.end_node.next
        return OutputContext(markdown="".join(markdown_parts), end_node=end_node)

    def _select_converter(
        self,
        context: InputContext,
    ) -> ConverterProtocol | None:
        node = context.current_node

        tag = node.tag or ""
        candidates = self._tagged_converters.get(tag, [])

        for converter in candidates:
            if converter.predicate(context):
                return converter

        for converter in self._unbounded_converters:
            if converter.predicate(context):
                return converter

        return None
