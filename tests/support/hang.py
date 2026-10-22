"""A stand-in for a Bot operation that never ends."""

import asyncio


async def hang(*args: object, **kwargs: object) -> None:
    del args, kwargs
    await asyncio.Event().wait()
