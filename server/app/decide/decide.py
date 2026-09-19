"""DECIDE: one structured-output call that proposes how to answer this turn.

Returns an explicit Decision object (strategy, template, provider params,
coverage, gaps, reason), not a vibe. The prompt lists only what the persona may
do and only the templates it may use; policy.py still enforces both, because
the model can propose anything. Unlike A2UI documents, this schema is small
enough for strict structured outputs.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from ..config import settings
from ..data.providers import REGISTRY
from ..generation.llm import chat_model
from ..templates.store import Manifest
from .policy import Persona

Strategy = Literal["TEXT", "TEMPLATE", "ADAPT", "GENERATE", "REFINE"]


class ProviderParam(BaseModel):
    name: str = Field(description="A param name declared by the template's data provider.")
    value: str = Field(description="The value, as a string (numbers like 60, booleans as true/false).")


class Decision(BaseModel):
    intent: str = Field(description="What the user wants, in a few words.")
    strategy: Strategy
    templateId: str | None = Field(description="The chosen template id for TEMPLATE/ADAPT, else null.")
    params: list[ProviderParam] = Field(description="Data provider params for the template; empty if none apply.")
    coverage: Literal["full", "partial", "none"] = Field(
        description="How much of the request the best template covers."
    )
    gaps: list[str] = Field(description="What the best template does NOT cover; empty when coverage is full.")
    dataProviders: list[str] = Field(
        description="For GENERATE: the data providers whose REAL data the new UI needs (names as listed); else empty."
    )
    target: str | None = Field(
        description="For REFINE: the id of the on-screen surface to change, exactly as listed (e.g. var-2); else null."
    )
    reason: str = Field(description="One short sentence explaining the choice.")


@dataclass(frozen=True)
class TurnContext:
    """What DECIDE knows beyond the messages (P6): a UI action and the user's choices so far."""

    action: dict[str, Any] | None = None  # A2UI client action: {name, context, sourceComponentId, surfaceId}
    source: Manifest | None = None  # the template whose surface emitted the action
    suggested: tuple[Manifest, ...] = ()  # source.suggestedNext, as hints
    selections: dict[str, Any] = field(default_factory=dict)  # merged action contexts, persisted per thread
    screen: tuple[str, ...] = ()  # P8: the thread's surfaces (lineage.screen_lines), for REFINE targets


def turn_context(
    action: dict[str, Any] | None,
    prior_selections: dict[str, Any] | None,
    every: list[Manifest],
    usable: list[Manifest],
    screen: list[str] | None = None,
) -> tuple[TurnContext, dict[str, Any]]:
    """Build DECIDE's context for a turn. Returns (context, newly chosen scalar values)."""
    chosen: dict[str, Any] = {}
    source = None
    if action:
        chosen = {k: v for k, v in action.get("context", {}).items() if isinstance(v, (str, int, float, bool))}
        source = next((m for m in every if action["name"] in m.events), None)
    ctx = TurnContext(
        action=action,
        source=source,
        suggested=tuple(m for m in usable if source and m.id in source.suggested_next),
        selections={**(prior_selections or {}), **chosen},
        screen=tuple(screen or ()),
    )
    return ctx, chosen


DecideFn = Callable[..., Awaitable[Decision]]  # (messages, persona, manifests, context: TurnContext | None)

STRATEGY_HELP = {
    "TEXT": "Answer in prose. For conceptual questions, explanations and chit-chat where no screen would help.",
    "TEMPLATE": "Show a curated template, filled with real data from its provider. Narrowing that data with the "
                "provider's params (a price limit, one specific item…) still counts as full coverage.",
    "ADAPT": "Start from a curated template and propose design variants that change its structure to close gaps in "
             "the request (e.g. \"add delivery info to the product view\"). Set templateId to that template and "
             "list the gaps. The designer sees the production screen plus the variants.",
    "GENERATE": "Compose new UI from the design system's components, for UI requests no template covers, including "
                "recommendations or comparisons across the options for the user's situation (e.g. which option fits "
                "their needs), where a purpose-built view helps more than prose.",
    "REFINE": "Modify ONE surface already on screen (listed under Context by id) and nothing else, e.g. \"make the "
              "button green\", \"add a badge on option 3\", \"make variant 2's title shorter\". Set target to its id; "
              "when the user doesn't say which, use the one marked [latest]. \"Option/variant/version N\" means var-N. "
              "A request to change what's showing is REFINE, not a new UI.",
}


def _scalar_selections(selections: dict[str, Any]) -> str:
    items = [f"{k}={v}" for k, v in selections.items() if isinstance(v, (str, int, float, bool)) and v != ""]
    return ", ".join(items)


def context_block(ctx: TurnContext | None) -> str:
    if ctx is None:
        return ""
    lines = []
    if ctx.action:
        where = f' on the "{ctx.source.title}" screen ({ctx.source.id})' if ctx.source else ""
        meaning = f" Meaning: {ctx.source.events.get(ctx.action['name'])}" if ctx.source and ctx.action["name"] in ctx.source.events else ""
        lines.append(
            f"The latest turn is a UI action, not typed text: the user triggered \"{ctx.action['name']}\"{where}.{meaning}\n"
            f"  Action context: {json.dumps(ctx.action.get('context', {}), ensure_ascii=False)[:1500]}"
        )
        if ctx.suggested:
            names = ", ".join(f"{m.id} ({m.title})" for m in ctx.suggested)
            lines.append(
                f"The design team suggests these next screens after that one: {names}. They're hints, not rules: "
                "choose what best serves the user. When nothing further needs showing, acknowledge the choice in TEXT."
            )
        elif ctx.source:
            lines.append(
                "That screen has no suggested next screen, so this action completes its flow: acknowledge it in TEXT "
                "and summarize what the user chose. Don't build a confirmation UI (it would need data no provider has)."
            )
    if ctx.screen:
        lines.append("Surfaces on screen in this conversation (REFINE targets, by id):\n"
                     + "\n".join(f"    {s}" for s in ctx.screen))
    chosen = _scalar_selections(ctx.selections)
    if chosen:
        lines.append(f"Values the user has chosen on screen so far (use them for params when relevant): {chosen}")
    return ("\n\nContext:\n" + "\n".join(f"- {line}" for line in lines)) if lines else ""


def explorer_rules(persona: Persona) -> str:
    """Extra rules for personas that may change curated screens (the explorer)."""
    lines = []
    if "ADAPT" in persona.strategies:
        lines.append("- ADAPT needs an explicit change instruction (add, remove, move, emphasize, restructure). A request "
                     "only to see or show something (e.g. \"show me the products\", \"show me the details\") is never ADAPT: "
                     "choose TEMPLATE with the closest curated screen, which is the production baseline to explore from, "
                     "even if it covers the request only partly. When the request changes or extends what a template "
                     "shows, choose ADAPT with that template, even if it's not on screen yet.")
    if "REFINE" in persona.strategies:
        lines.append("- When the request is about a surface already on screen (see Context), choose REFINE with its "
                     "id as target. With no surfaces on screen, never choose REFINE.")
        lines.append("- Designers name variants as \"option N\", \"variant N\", \"version N\" or by their title: that's "
                     "var-N (or the titled one). Target a baseline only when they name the baseline, production or "
                     "original screen, or when no variants are on screen.")
    return ("\n" + "\n".join(lines)) if lines else ""


def build_decide_prompt(persona: Persona, manifests: list[Manifest], ctx: TurnContext | None = None) -> str:
    strategies = "\n".join(f"- {s}: {STRATEGY_HELP[s]}" for s in persona.strategies)
    if manifests:
        blocks = []
        for m in manifests:
            provider = REGISTRY.get(m.provider)
            data = provider.describe() if provider else f"{m.provider} (unavailable)"
            examples = "; ".join(f'"{e}"' for e in m.examples)
            blocks.append(f'- {m.id} ("{m.title}"): {m.intent}.\n  Examples: {examples}\n  Data: {data}')
        templates = "\n".join(blocks)
    else:
        templates = "(none)"
    providers = "\n".join(p.describe() for p in REGISTRY.values())
    return f"""You decide how a generative-UI assistant answers the user's latest message.

Persona: {persona.name}. {persona.description}

Strategies you may choose:
{strategies}

Curated templates (designed and approved by the design team; prefer them when they cover the request):
{templates}

Data providers (the only source of real names, prices and features):
{providers}

Rules:
- Choose TEMPLATE only when a template's intent covers what the user wants to see. A similar topic is not enough:
  advice, comparisons or recommendations for the user's situation are not "show the list".
- Coverage is full only when every need in the request is met by the template's intent or by one of its provider's
  params. A need no param can express (the user's situation, habits or priorities, "which one suits me") is a gap:
  a screen that lists every option leaves that choice to the user. Then choose GENERATE, not TEMPLATE.
- For TEMPLATE, set templateId and fill params ONLY from that template's provider params, as strings. Leave params
  empty when the user gave no constraint. Never invent param names or values the user didn't imply.
- Set coverage and gaps against the best-matching template, even when you don't choose it.
- Choose TEXT for conceptual questions and conversation. Choosing among the options on offer is not conceptual:
  prefer a UI (TEMPLATE if one covers it, else GENERATE).
- Data (names, prices, features) always comes from providers, never from you. For GENERATE, list in
  dataProviders every provider whose data the new UI needs (e.g. the list provider when recommending one of its items).
- Keep reason to one short sentence.""" + explorer_rules(persona) + context_block(ctx)


def make_decide_model() -> BaseChatModel:
    return chat_model(settings.router_model, temperature=0)


def make_decide(model: BaseChatModel | None = None, history: int = 6) -> DecideFn:
    structured = (model or make_decide_model()).with_structured_output(Decision, method="json_schema", strict=True)

    async def decide(
        messages: Sequence[BaseMessage], persona: Persona, manifests: list[Manifest], context: TurnContext | None = None
    ) -> Decision:
        recent = [m for m in messages if isinstance(m, (HumanMessage, AIMessage))][-history:]
        return await structured.ainvoke([SystemMessage(build_decide_prompt(persona, manifests, context)), *recent])

    return decide
