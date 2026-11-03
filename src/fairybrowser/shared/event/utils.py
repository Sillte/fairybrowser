from typing import Any, Callable, TypeGuard, overload

from typing_extensions import TypeIs

from .domain import Disposable, Event, Listener


def once[T](event: Event[T]) -> Event[T]:
    def subscribe(listener: Listener[T]) -> Disposable:
        alive_disposable: Disposable | None = None

        def wrapper(value: T) -> None:
            nonlocal alive_disposable
            if alive_disposable is None:
                return
            listener(value)
            alive_disposable.dispose()
            alive_disposable = None

        alive_disposable = event.subscribe(wrapper)
        return Disposable(lambda: alive_disposable.dispose() if alive_disposable is not None else None)

    return Event(subscribe)


def map_event[T, U](event: Event[T], transform: Callable[[T], U]) -> Event[U]:
    """If the source of event is disposed, then the returned Event is not fired."""

    def subscribe(listener: Listener[U]) -> Disposable:
        return event.subscribe(lambda value: listener(transform(value)))

    return Event[U](subscribe)


@overload
def filter[T, R](
    event: Event[T],
    predicator: Callable[[T], TypeIs[R]],
) -> Event[R]: ...


@overload
def filter[T, R](
    event: Event[T],
    predicator: Callable[[T], TypeGuard[R]],
) -> Event[R]: ...


@overload
def filter[T](
    event: Event[T],
    predicator: Callable[[T], bool],
) -> Event[T]: ...


def filter[T](event: Event[T], predicator: Callable[[T], bool]) -> Event[Any]:
    def subscribe(listener: Listener[T]) -> Disposable:
        def wrapper(value: T) -> None:
            if predicator(value):
                listener(value)

        disposable = event.subscribe(wrapper)
        return Disposable(lambda: disposable.dispose())

    return Event(subscribe)
