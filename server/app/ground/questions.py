"""What to ASK the knowledge base: the user's words are not a retrieval query (P7, D2).

"Change the colour of the badge to yellow" carries no design-system vocabulary, no
screen and no history. Sent to a RAG over the design system's documentation it
matches on "colour" and "yellow" and comes back about the wrong thing — the answer
looks plausible and can't be trusted, which is worse than no answer.

So one small structured call runs first. Given the request, the conversation so far,
what is on the screen being changed and the props those components actually take, it
reasons about what it needs to know and writes standalone questions:

    "Which values does Badge.backgroundColor accept in this design system?"
    "When is a yellow badge appropriate, and what content or contrast rules apply?"

Each question is then its own `guidelines.search`, so the RAG answers what was asked
and the trace panel shows the questions next to the answers.

Never blocks a turn: a failed call, no usable questions, or GROUND_QUESTIONS=off all
fall back to `Ask.fallback()` ("<intent>. <request>", what GROUND used to send), which
retrieves less well but retrieves.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from ..config import settings
from ..explore.patching import to_view
from ..generation.llm import chat_model
from ..grounding.catalog import generation_catalog

MOST = 3  # questions per turn: each one is a RAG call
VOCABULARY = "componentsTheDesignSystemHas"  # the inputs key holding the catalog names


class RetrievalQuestions(BaseModel):
    need: str = Field(description="What you must know from the design system to do this correctly, in one sentence.")
    questions: list[str] = Field(
        description="One to three standalone questions for the design system's documentation, most important first."
    )


QuestionsFn = Callable[[str, dict[str, Any]], Awaitable[RetrievalQuestions]]  # (system prompt, inputs) -> questions


QUESTIONS_PROMPT = """You write the queries for a retrieval system over a design system's own documentation:
component rules, design tokens, approved patterns, content and accessibility guidance.

The user's message is not a query. It is short, it points at things on screen ("the badge", "that button"), and it
says what the user wants rather than what you need to know. Work out what you must know FROM THE DESIGN SYSTEM to
carry the request out correctly, and write that as one to three standalone questions.

- Resolve what the message refers to from the conversation and from what is on the screen, and name it in the
  design system's own vocabulary: use the component and prop names you are given, and never invent others.
- Ask what the design system allows and requires: which values a prop accepts, which tokens exist, when a variant
  or pattern is appropriate, which content, copy and accessibility rules apply. Never ask the documentation to
  make the change, and never ask what the user should want.
- Each question must stand alone: someone who reads only that question, with no conversation and no screen in
  front of them, must understand what is being asked. Never write "it", "this" or "the one above".
- AT MOST 20 WORDS per question, one thing each. No "and" joining two different asks, no "specifically", no
  examples in brackets, no lists of candidate names. A short question retrieves far better than a long one;
  when you want two things, ask two questions.
  The shapes that work: "Which values does <Component>.<prop> accept?" · "When is <value> appropriate for
  <Component>?" · "What contrast rules apply to <Component> text?" · "Which pattern covers <short purpose>?"
- Ask only what this request needs; one precise question beats three vague ones. When a value is being set, it is
  usually worth asking both which values are allowed and when each of them is appropriate.
- Order them most important first."""


def make_questions_fn(model: BaseChatModel | None = None) -> QuestionsFn:
    if model is None:
        # Convergent step, and it runs on every grounded turn: the small model, no temperature.
        model = chat_model(settings.router_model, temperature=0)
    structured = model.with_structured_output(RetrievalQuestions, method="json_schema", strict=True)

    async def questions(system: str, inputs: dict[str, Any]) -> RetrievalQuestions:
        return await structured.ainvoke([
            SystemMessage(system),
            HumanMessage(json.dumps(inputs, ensure_ascii=False, indent=1, default=str)),
        ])

    return questions


@dataclass
class Ask:
    """What the retrieval questions are written from, and the query to use if they can't be."""

    request: str  # the user's latest message, as they wrote it
    intent: str = ""  # DECIDE's reading of it
    doing: str = ""  # what this turn is about to do, in words ("changing Variant 2")
    history: list[str] = field(default_factory=list)  # the conversation so far, oldest first
    screen: dict[str, list[str]] = field(default_factory=dict)  # component -> its props, for the screen in play
    gaps: list[str] = field(default_factory=list)  # what the curated screens don't cover (DECIDE)

    def fallback(self) -> list[str]:
        """The query GROUND used before questions existed: better than nothing when the call fails."""
        return [f"{self.intent}. {self.request}".strip(". ") or self.request]

    def as_inputs(self) -> dict[str, Any]:
        out: dict[str, Any] = {"task": self.doing, "userMessage": self.request, "whatTheUserWants": self.intent}
        if self.history:
            out["conversationSoFar"] = self.history
        if self.screen:
            out["componentsOnTheScreen"] = self.screen
        if self.gaps:
            out["notCoveredByTheCuratedScreens"] = self.gaps
        # The vocabulary to ask in. Without it the questions name components the design system
        # doesn't have (a new screen has no components on screen to go by).
        out[VOCABULARY] = generation_catalog()["names"]
        return {k: v for k, v in out.items() if v}


def screen_components(doc: dict[str, Any]) -> dict[str, list[str]]:
    """Each component type on the screen and the props the design system gives it.

    The props are the catalog's, not the ones the screen happens to set: the question is
    often about a prop nobody has set yet ("the badge has no backgroundColor — which
    values does it take?").
    """
    catalog = generation_catalog()["components"]
    used = {b.get("component") for b in to_view(doc)["components"].values()}
    return {name: _props(catalog[name]) for name in sorted(n for n in used if isinstance(n, str) and n in catalog)}


def _props(schema: dict[str, Any]) -> list[str]:
    parts = [schema, *(p for p in schema.get("allOf") or [] if isinstance(p, dict))]
    names = [k for part in parts for k in (part.get("properties") or {}) if k != "component"]
    return sorted(dict.fromkeys(names))
