"""Small shared utilities for deterministic background services."""
import asyncio
import logging
import math

logger = logging.getLogger(__name__)


def seconds(value: float, *, minimum: float = 0) -> float:
    value = float(value)
    if not math.isfinite(value) or value < minimum:
        raise ValueError(f"seconds must be finite and >= {minimum}")
    return value


def start_loop(name, callback, interval):
    async def run():
        while True:
            try:
                await callback()
            except Exception:
                logger.exception("%s pass failed; retrying next interval", name)
            await asyncio.sleep(interval)
    return asyncio.create_task(run(), name=name)
