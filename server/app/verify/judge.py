"""Soft rules via an LLM judge (the guideline gate's second half, P7).

Hard rules are code (lints.py). Soft guidance ("recommend with reasons", "badges
are for highlights") needs judgment, so a model reviews the surface against ONLY
the rules retrieved for this request and reports clear violations, each citing a
rule id. Unknown ids are dropped: the judge can't invent rules.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from ..config import settings
from ..generation.llm import chat_model
from ..grounding.sources import Source


class SoftViolation(BaseModel):
    ruleId: str = Field(description="The id of the rule that is violated, exactly as given.")
    componentIds: list[str] = Field(description="Ids of the components involved.")
    problem: str = Field(description="What is wrong, in one sentence.")
    fix: str = Field(description="How to fix it, in one sentence.")


class Verdict(BaseModel):
    violations: list[SoftViolation] = Field(description="Clear violations only; empty when the UI follows the rules.")


# (doc, rules, request, change=None). `change` (P8): the UI is a variant of an approved
# screen, and this lists what changed; only violations the change introduces count.
JudgeFn = Callable[..., Awaitable[list[SoftViolation]]]

CHANGE_SCOPE = """
This UI is a VARIANT of a design-approved production screen. Judge ONLY what the change below introduces or
makes worse. Anything that was already true of the production screen (its structure, which items carry what
from data, its wording) is approved and out of scope, even where a rule would otherwise apply.
Change against the production screen:
{change}"""


def judge_prompt(rules: list[Source]) -> str:
    listed = "\n\n".join(f"{r.cite()}\n{r.text}" for r in rules)
    return f"""You review a generated UI (A2UI v0.9 JSON: a flat component list, bindings as {{"path": ...}}) against
the design guidelines below. Report only CLEAR violations of these specific rules, citing the rule id exactly.
Don't invent rules, don't report stylistic preferences, and don't report anything the rules don't cover.
Bound values ({{"path": ...}}) come from real data: judge the structure, not the data.

Guidelines:
{listed}"""


def make_judge(model: BaseChatModel | None = None) -> JudgeFn:
    if model is None:
        model = chat_model(settings.router_model, temperature=0)
    structured = model.with_structured_output(Verdict, method="json_schema", strict=True)

    async def judge(doc: Any, rules: list[Source], request: str, change: str | None = None) -> list[SoftViolation]:
        if not rules:
            return []
        system = judge_prompt(rules) + (CHANGE_SCOPE.format(change=change) if change else "")
        verdict = await structured.ainvoke([
            SystemMessage(system),
            HumanMessage(f"User request: {request}\n\nUI:\n{json.dumps(doc, ensure_ascii=False, separators=(',', ':'))}"),
        ])
        known = {r.id for r in rules}
        return [v for v in verdict.violations if v.ruleId in known]

    return judge


def violation_message(v: SoftViolation, rules: list[Source]) -> str:
    rule = next((r for r in rules if r.id == v.ruleId), None)
    head = f"Guideline {rule.cite()}" if rule else f"Guideline [{v.ruleId}]"
    where = f" (component {', '.join(v.componentIds)})" if v.componentIds else ""
    return f"{head}{where}: {v.problem} Fix: {v.fix}"
