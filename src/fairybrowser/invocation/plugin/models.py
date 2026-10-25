from abc import ABC, abstractmethod
from pathlib import Path
from typing import Callable

from fairybrowser.invocation.models import InvocationConfiguration, InvocationExecutor, InvocationProtocol


class InvocationPlugin[InputT, ResultT](ABC):
    """Base class for class-based invocation plugins."""

    @classmethod
    def execute(
        cls,
        input: InputT,
        configuration: InvocationConfiguration | None = None,
        *,
        output_folder: Path | None = None,
    ) -> ResultT:
        """Create and execute this plugin's invocation."""
        plugin = cls()
        executor = InvocationExecutor.from_any(plugin.create_invocation())
        return executor.invoke(input, configuration=configuration, output_folder=output_folder)

    @abstractmethod
    def create_invocation(self) -> InvocationProtocol[InputT, ResultT]:
        """Create the invocation implementation for this plugin."""
        raise NotImplementedError


def invocation_plugin[S, T](
    factory: Callable[[], InvocationProtocol[S, T]],
) -> Callable[[], InvocationProtocol[S, T]]:
    """Mark a top-level factory function as an invocation plugin."""
    setattr(factory, "__fairybrowser_invocation_plugin__", True)
    return factory


def execute_plugin[S, T](
    factory: Callable[[], InvocationProtocol[S, T]],
    input: S,
    configuration: InvocationConfiguration | None = None,
    *,
    output_folder: Path | None = None,
) -> T:
    return InvocationExecutor.from_any(factory()).invoke(
        input, configuration=configuration, output_folder=output_folder
    )
