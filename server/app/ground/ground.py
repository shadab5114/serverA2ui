"""GROUND: turn a GENERATE request into a design brief before building (P7).

  guidelines.search   local markdown now, RAG later (sources.Guidelines)
  mcp.resolve_intent  components the design system's MCP server suggests
  <provider>          REAL data the UI needs (DECIDE's dataProviders): the
                      generator must seed and bind it, never invent values
  design_brief        one structured call: pattern, components, layout, the
                      rules that apply (each cited) and which data to show

Divergent thinking happens here (the brief); convergent building happens in the
generator. The brief, data and cited rules are appended to the user's request as
`guidance`, and the retrieved soft rules go to the guideline judge.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from ..config import settings
from ..data.providers import REGISTRY
from ..generation.llm import chat_model
from ..graph.trace import Tracer
from ..grounding.catalog import generation_catalog
from ..grounding.mcp import CatalogMcp
from ..grounding.sources import Guidelines, GroundingResult, Source


class BriefRule(BaseModel):
    id: str = Field(description="A guideline id from the retrieved guidelines, exactly as given.")
    how: str = Field(description="How it applies to this UI, in one short sentence.")


class DesignBrief(BaseModel):
    pattern: str = Field(description='The approved pattern id that fits (e.g. "PAT-301"), or "none".')
    patternWhy: str = Field(description="Why this pattern (or none), in one sentence.")
    components: list[str] = Field(description="Catalog component names to use.")
    layout: str = Field(description="The composition, top to bottom, in two or three sentences.")
    rules: list[BriefRule] = Field(description="The guidelines that apply and how.")
    dataUse: str = Field(description='Which data fields to show and how to bind them, or "no data".')


BriefFn = Callable[[str, dict[str, Any]], Awaitable[DesignBrief]]  # (system prompt, inputs) -> brief


BRIEF_PROMPT = """You are the design lead writing a short DESIGN BRIEF for a UI generator that builds with a design
system's components (A2UI). Choose the approved pattern that fits the request (or "none" and compose freely),
pick the components, describe the layout, cite the guidelines that apply and say how, and say which of the
given data fields to show. Be inventive about structure, but stay within the cited rules, use only catalog
component names, and never invent data: only the given data exists."""


def make_brief_fn(model: BaseChatModel | None = None) -> BriefFn:
    if model is None:
        # Divergent step: some temperature where the model family allows it.
        model = chat_model(settings.router_model, temperature=0.7)
    structured = model.with_structured_output(DesignBrief, method="json_schema", strict=True)

    async def brief(system: str, inputs: dict[str, Any]) -> DesignBrief:
        return await structured.ainvoke([
            SystemMessage(system),
            HumanMessage(json.dumps(inputs, ensure_ascii=False, indent=1, default=str)),
        ])

    return brief


@dataclass
class Grounding:
    brief: dict[str, Any]
    sources: list[dict[str, Any]]  # every guideline/pattern/component source, serializable
    data: dict[str, Any]  # merged provider outputs the UI must use
    guidance: str  # appended to the generator's request
    notes: list[str] = field(default_factory=list)

    def soft_rules(self) -> list[Source]:
        return [Source(**s) for s in self.sources if Source(**s).kind in ("soft", "pattern")]


def _merge_data(outputs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Providers' outputs merged at the root (first wins on a key clash), so paths stay short: /plans, /addons."""
    merged: dict[str, Any] = {}
    for out in outputs.values():
        for k, v in out.items():
            merged.setdefault(k, v)
    return merged


def guidance_text(brief: DesignBrief, rules: list[Source], data: dict[str, Any]) -> str:
    by_id = {r.id: r for r in rules}
    lines = [
        "Design brief (follow it):",
        f"- Pattern: {brief.pattern} ({brief.patternWhy})",
        f"- Layout: {brief.layout}",
        f"- Components: {', '.join(brief.components)}",
        f"- Data: {brief.dataUse}",
        "- Guidelines that apply:",
    ]
    for r in brief.rules:
        text = f" {by_id[r.id].title}:" if r.id in by_id else ""
        lines.append(f"  - {r.id}{text} {r.how}")
    if data:
        lines += [
            "",
            "Real data (the ONLY source of names, prices and features): seed exactly this object with one "
            'updateDataModel at path "/" and bind to it with {"path": ...}. Never write these values as literal '
            "text, and don't invent any others. Omit fields the brief doesn't need.",
            json.dumps(data, ensure_ascii=False, separators=(",", ":")),
        ]
    return "\n".join(lines)


class Grounder:
    def __init__(
        self,
        guidelines: Guidelines | None = None,
        mcp: CatalogMcp | None = None,
        brief: BriefFn | None = None,
    ) -> None:
        self.guidelines = guidelines or Guidelines()
        self.mcp = mcp
        self._brief = brief

    @property
    def brief_fn(self) -> BriefFn:
        if self._brief is None:
            self._brief = make_brief_fn()
        return self._brief

    async def retrieve(
        self, query: str, tracer: Tracer, *, mcp_intent: str | None = None, k: int = 6
    ) -> tuple[GroundingResult, GroundingResult, list[str]]:
        """(guidelines, components, notes): the traced lookups, without a brief.
        ADAPT/REFINE use this directly: each variant carries its own rationale and citations."""
        notes: list[str] = []
        async with tracer.tool(self.guidelines.name + ".search", {"query": query}) as call:
            found = await self.guidelines.search(query, k=k)
            call.set(_summary(found, "guideline"), sources=[asdict(s) for s in found.sources], note=found.note)
        if found.note:
            notes.append(found.note)

        components = GroundingResult("", [], "MCP not configured")
        if self.mcp is not None:
            # The catalog server matches component vocabulary, so ask it with the best pattern's
            # composition when one was retrieved (the user's words rarely name components).
            pattern = next((s for s in found.sources if s.kind == "pattern"), None)
            intent = mcp_intent or (f"{pattern.title}. {pattern.text}" if pattern else query)
            async with tracer.tool("mcp.resolve_intent_to_schema", {"intent": intent[:500], "limit": 6}) as call:
                try:
                    components = await self.mcp.resolve_intent(intent, limit=6)
                except Exception as err:  # noqa: BLE001 — MCP is optional grounding
                    components = GroundingResult("", [], f"MCP call failed: {err}")
                call.set(_summary(components, "component"), sources=[asdict(s) for s in components.sources], note=components.note)
        if components.note:
            notes.append(components.note)
        return found, components, notes

    async def ground(self, request: str, plan: dict[str, Any], tracer: Tracer) -> Grounding:
        query = f"{plan.get('intent') or ''}. {request}".strip(". ")
        found, components, notes = await self.retrieve(query, tracer)

        outputs: dict[str, dict[str, Any]] = {}
        for name in plan.get("dataProviders") or []:
            provider = REGISTRY.get(name)
            if provider is None:
                continue
            async with tracer.tool(name, {}) as call:
                outputs[name] = provider.call({})
                call.set(f"{', '.join(f'{len(v)} {k}' for k, v in outputs[name].items() if isinstance(v, list))} loaded",
                         data=outputs[name])
        data = _merge_data(outputs)

        inputs = {
            "request": request,
            "intent": plan.get("intent"),
            "gapsInCuratedTemplates": plan.get("gaps") or [],
            "guidelines": [{"id": s.id, "title": s.title, "text": s.text} for s in found.sources],
            "suggestedComponents": [s.title for s in components.sources],
            "catalogComponents": generation_catalog()["names"],
            "dataFields": {k: _shape(v) for k, v in data.items()},
        }
        async with tracer.tool("design_brief", {"pattern candidates": [s.id for s in found.sources if s.kind == "pattern"]}) as call:
            brief = await self.brief_fn(BRIEF_PROMPT, inputs)
            call.set(f"{brief.pattern}: {brief.layout}", brief=brief.model_dump())

        sources = found.sources + components.sources
        return Grounding(
            brief=brief.model_dump(),
            sources=[asdict(s) for s in sources],
            data=data,
            guidance=guidance_text(brief, found.sources, data),
            notes=notes,
        )


def _summary(res: GroundingResult, noun: str) -> str:
    if not res.sources:
        return f"no {noun}s" + (f" ({res.note})" if res.note else "")
    return f"{len(res.sources)} {noun}s: {', '.join(s.id for s in res.sources)}" + (f" ({res.note})" if res.note else "")


def _shape(value: Any) -> Any:
    """A compact description of a data value's shape for the brief (field names, not values)."""
    if isinstance(value, list):
        return [_shape(value[0])] if value else []
    if isinstance(value, dict):
        return {k: _shape(v) for k, v in value.items()}
    return type(value).__name__
