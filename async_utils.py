from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Any, Callable, TypeVar

T = TypeVar("T")

_BLOCKING_POOL = ThreadPoolExecutor(max_workers=8, thread_name_prefix="alarmfw-api")


async def run_blocking(func: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
    loop = asyncio.get_running_loop()
    call = partial(func, *args, **kwargs)
    return await loop.run_in_executor(_BLOCKING_POOL, call)
