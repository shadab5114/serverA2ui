"""The graph's state, shared by every node (playground.py, explore.py)."""

from __future__ import annotations

from typing import Annotated, Any

from langchain_core.messages import HumanMessage
from langgraph.graph import MessagesState


def merge_dicts(old: dict | None, new: dict | None) -> dict:
    return {**(old or {}), **(new or {})}


class GraphState(MessagesState):
    persona: str
    plan: dict[str, Any]  # Plan.as_meta() of the current turn
    action: dict[str, Any] | None  # the A2UI client action that started this turn, if any (P6)
    selections: Annotated[dict[str, Any], merge_dicts]  # scalar values the user chose on screen, per thread
    grounding: dict[str, Any] | None  # GROUND's output for this turn's GENERATE (P7)
    surfaces: Annotated[dict[str, Any], merge_dicts]  # lineage of every surface shown, per thread (P8)
    last_surface: str | None  # the surface shown most recently: REFINE's default target (P8)


def last_user_text(state: GraphState) -> str:
    for m in reversed(state["messages"]):
        if isinstance(m, HumanMessage):
            c = m.content
            if isinstance(c, str):
                return c
            return "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in c)
    return ""
