import asyncio
from typing import Any, Awaitable, Callable, TypeVar

from telegram.error import RetryAfter

T = TypeVar("T")


async def tg_call(func: Callable[..., Awaitable[T]], *args: Any, **kwargs: Any) -> T:
    """Call a Telegram API coroutine with RetryAfter handling.

    The provided *func* is awaited with the given arguments. If Telegram
    responds with :class:`telegram.error.RetryAfter`, the call is retried
    after sleeping for the suggested delay.
    """
    while True:
        try:
            return await func(*args, **kwargs)
        except RetryAfter as e:  # pragma: no cover - network timing dependent
            await asyncio.sleep(e.retry_after)


__all__ = ["tg_call"]
