from types import TracebackType


class InvocationException(Exception):
    """Invocation error retaining the original exception and traceback."""

    def __init__(self, exception: Exception) -> None:
        self._exception = exception
        self.exception_type = type(exception).__name__
        self.message = str(exception)
        self._original_traceback = exception.__traceback__
        super().__init__(f"{self.exception_type}: {self.message}")

    @property
    def original_exception(self) -> Exception:
        return self._exception

    @property
    def original_traceback(self) -> TracebackType | None:
        return self._original_traceback
