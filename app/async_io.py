"""Run blocking MT5 / file IO off the asyncio event loop."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


async def run_blocking(func: Callable[..., T], *args, **kwargs) -> T:
    return await asyncio.to_thread(func, *args, **kwargs)
