"""Trace: make what the agent did visible (P7).

Nodes report steps and tool activity (grounding queries, data providers, the
decision, the brief, gate checks) as custom events; the AG-UI bridge turns them
into standard STEP_STARTED / STEP_FINISHED and TOOL_CALL_START / ARGS / END /
RESULT events, which the client's trace panel shows. Every result carries a short
human `summary` for the panel next to its full JSON.

Outside a graph run (e.g. the /generate endpoint) there is no run to report to,
so `Tracer.off()` makes every call a no-op.
"""

from __future__ import annotations

import contextlib
import uuid
from collections.abc import AsyncIterator
from typing import Any

from langchain_core.callbacks import adispatch_custom_event


class ToolCall:
    def __init__(self) -> None:
        self.result: dict[str, Any] = {}

    def set(self, summary: str, **details: Any) -> None:
        self.result = {"summary": summary, **details}


class Tracer:
    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled

    @classmethod
    def off(cls) -> Tracer:
        return cls(enabled=False)

    async def _emit(self, name: str, data: dict[str, Any]) -> None:
        if self.enabled:
            await adispatch_custom_event(name, data)

    @contextlib.asynccontextmanager
    async def step(self, name: str) -> AsyncIterator[None]:
        await self._emit("trace_step", {"name": name, "phase": "start"})
        try:
            yield
        finally:
            await self._emit("trace_step", {"name": name, "phase": "finish"})

    @contextlib.asynccontextmanager
    async def tool(self, name: str, args: dict[str, Any] | None = None) -> AsyncIterator[ToolCall]:
        call_id = f"tool_{uuid.uuid4().hex[:12]}"
        call = ToolCall()
        await self._emit("trace_tool_start", {"id": call_id, "name": name, "args": args or {}})
        try:
            yield call
        except Exception as err:
            call.set(f"failed: {err}", error=str(err))
            raise
        finally:
            await self._emit("trace_tool_end", {"id": call_id, "name": name, "result": call.result})


TRACE = Tracer()
