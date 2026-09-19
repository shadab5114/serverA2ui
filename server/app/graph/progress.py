"""Progress feedback for slow turns (follow-up F1).

The client shows the latest `CUSTOM status` text in the pending assistant bubble
until content or a surface arrives, so progress needs no client change: send a
status when the stage changes, and re-send it every second with the elapsed time
so a long wait visibly moves ("Checking the UI against the design system… 14s").
"""

from __future__ import annotations

import asyncio
import contextlib
import time

from langchain_core.callbacks import adispatch_custom_event

TICK_SECONDS = 1.0
_now = time.monotonic  # patched in tests (asyncio itself uses time.monotonic)


async def send_status(text: str) -> None:
    await adispatch_custom_event("status", {"text": text})


class StatusTicker:
    """Async context manager: `await ticker.stage("…")` to change the text; it re-sends with elapsed seconds."""

    def __init__(self, first_stage: str) -> None:
        self._stage = first_stage
        self._t0 = _now()
        self._task: asyncio.Task | None = None

    def _text(self) -> str:
        elapsed = int(_now() - self._t0)
        return f"{self._stage} {elapsed}s" if elapsed else self._stage

    async def stage(self, text: str) -> None:
        if text == self._stage:
            return  # already showing (and ticking) this stage
        self._stage = text
        await send_status(self._text())

    async def _tick(self) -> None:
        while True:
            await asyncio.sleep(TICK_SECONDS)
            await send_status(self._text())

    async def __aenter__(self) -> StatusTicker:
        await send_status(self._text())
        # Created inside the node, so the task inherits the run config that
        # adispatch_custom_event needs.
        self._task = asyncio.create_task(self._tick())
        return self

    async def __aexit__(self, *exc) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
