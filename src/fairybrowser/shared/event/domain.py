from __future__ import annotations

from threading import Lock
from typing import Any, Callable, Protocol, TypeGuard, overload

from typing_extensions import TypeIs

type Listener[T] = Callable[[T], Any]
type Dispose = Callable[[], None]


class Disposable:
    def __init__(self, dispose: Dispose):
        self._dispose = dispose

    def dispose(self) -> None:
        self._dispose()


type Subscribe[T] = Callable[[Listener[T]], Disposable]


class EventProtocol[T](Protocol):
    def subscribe(self, listener: Listener[T]) -> Disposable: ...

    def once(self) -> "EventProtocol[T]": ...

    def map[R](self, transform: Callable[[T], R]) -> "EventProtocol[R]": ...

    @overload
    def filter[R](
        self,
        predicate: Callable[[T], TypeIs[R]],
    ) -> "EventProtocol[R]": ...

    @overload
    def filter[R](
        self,
        predicate: Callable[[T], TypeGuard[R]],
    ) -> "EventProtocol[R]": ...

    @overload
    def filter(
        self,
        predicate: Callable[[T], bool],
    ) -> "EventProtocol[T]": ...

    def filter(self, predicate: Callable[[T], bool]) -> "EventProtocol[Any]": ...


class Event[T]:
    def __init__(self, subscribe: Subscribe[T]):
        self._subscribe = subscribe

    def subscribe(self, listener: Listener[T]) -> Disposable:
        return self._subscribe(listener)

    def __call__(self, listener: Listener[T]) -> Disposable:
        return self.subscribe(listener)

    def once(self) -> Event[T]:
        from fairybrowser.shared.event import utils

        return utils.once(self)

    def map[R](self, transform: Callable[[T], R]) -> Event[R]:
        from fairybrowser.shared.event import utils

        return utils.map_event(self, transform)

    @overload
    def filter[R](
        self,
        predicate: Callable[[T], TypeIs[R]],
    ) -> Event[R]: ...

    @overload
    def filter[R](
        self,
        predicate: Callable[[T], TypeGuard[R]],
    ) -> Event[R]: ...

    @overload
    def filter(
        self,
        predicate: Callable[[T], bool],
    ) -> Event[T]: ...

    def filter(self, predicate: Callable[[T], bool]) -> Event[Any]:
        from fairybrowser.shared.event import utils

        return utils.filter(self, predicate)


class EventEmitter[T]:
    """Thread-safe event source; listeners run outside the emitter lock."""

    def __init__(self) -> None:
        self._listeners: list[Listener[T]] = []
        self._lock = Lock()
        self.event = Event[T](self._subscribe)

    def _subscribe(self, listener: Listener[T]) -> Disposable:
        with self._lock:
            self._listeners.append(listener)

        def dispose() -> None:
            with self._lock:
                try:
                    self._listeners.remove(listener)
                except ValueError:
                    pass

        return Disposable(dispose)

    def fire(self, value: T) -> None:
        with self._lock:
            listeners = tuple(self._listeners)
        for listener in listeners:
            listener(value)

    def dispose(self) -> None:
        with self._lock:
            self._listeners.clear()
