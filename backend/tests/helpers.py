"""Small shared test helpers."""

from collections.abc import AsyncIterator


async def take[T](it: AsyncIterator[T], n: int) -> AsyncIterator[T]:
    count = 0
    async for item in it:
        yield item
        count += 1
        if count >= n:
            return
