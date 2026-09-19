"""The validator gate + bounded repair loop (reference: agent/uiGenerator.js).

Nothing reaches the wire until it validates:

  generate_a2ui -> validate_and_repair_graph (orphans) -> validate_a2ui_document (gate)
       ^                                                          |
       +---------- repair prompt (prev JSON + errors) <-----------+  (A2UI_MAX_REPAIRS retries)

Returns {ok: True, a2ui, meta, attempts} or {ok: False, errors, attempts, last_doc}
so the graph node can fall back to a plain-text apology instead of crashing.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from functools import cache
from typing import Any

from ..config import settings
from ..grounding.catalog import generation_catalog
from ..graph.trace import Tracer
from ..grounding.sources import Source
from ..log import RequestLogger
from ..verify.judge import JudgeFn, violation_message
from ..verify.lints import LINTS, lint_messages
from .gate import validate_a2ui_document
from .graph_check import validate_and_repair_graph
from .llm import Generation, generate_a2ui
from .prompt import build_system_prompt, schema_json

GenerateFn = Callable[[str, str], Awaitable[Generation]]
StatusFn = Callable[[str], Awaitable[None]]

STAGE_GENERATE = "Generating UI from the design system's components…"
STAGE_JUDGE = "Checking the UI against the design guidelines…"


def stage_repair(issues: int, attempt: int, total: int) -> str:
    noun = "issue" if issues == 1 else "issues"
    return f"Fixing {issues} {noun} the design-system check found (attempt {attempt} of {total})…"


@cache
def system_prompt() -> str:
    """Embeds the whole catalog, so it's built once and reused across turns."""
    return build_system_prompt(generation_catalog())


def collect_errors(graph_validation: dict, schema_validation: dict) -> list[str]:
    """Flatten graph + schema failures into short lines the model can act on."""
    errors = list(graph_validation["errors"])
    for f in schema_validation["failures"]:
        errors.append(f'Component "{f["id"]}" ({f["component"]}): {"; ".join(f["issues"])}')
    return errors


def build_repair_prompt(user_prompt: str, rejected_doc: Any, errors: list[str]) -> str:
    """Retry prompt: original ask + the exact errors + the rejected JSON."""
    return (
        f"{user_prompt}\n\n"
        "Your previous A2UI JSON was REJECTED by the validator (schema and design guidelines). Fix ONLY these "
        "errors and return the corrected, complete JSON object (same output "
        'contract — a single { "a2ui": [...] } object, no prose):\n\n'
        "Errors:\n" + "\n".join(f"- {e}" for e in errors) + "\n\n"
        f"Previous (invalid) JSON:\n{schema_json(rejected_doc)}"
    )


async def generate_validated_a2ui(
    user_prompt: str,
    *,
    max_repairs: int | None = None,
    log: RequestLogger | None = None,
    generate: GenerateFn = generate_a2ui,
    on_status: StatusFn | None = None,
    guidance: str = "",
    soft_rules: list[Source] | None = None,
    judge: JudgeFn | None = None,
    tracer: Tracer | None = None,
    repair_soft: bool = True,
) -> dict[str, Any]:
    """guidance: the design brief + real data + rules from GROUND, appended to the user's request (P7).
    soft_rules + judge: the guideline judge, run once a candidate passes the schema gate and the hard-rule lints.
    repair_soft: False ships the first valid UI with the judge's findings as flags (persona policy "flag", P8)."""
    max_repairs = settings.max_repairs if max_repairs is None else max_repairs
    tracer = tracer or Tracer.off()
    soft_rules = soft_rules or []
    total = max_repairs + 1
    request = f"{user_prompt}\n\n{guidance}" if guidance else user_prompt
    prompt_for_model = request
    last_doc: Any = None
    last_errors: list[str] = []
    flags: list[dict[str, Any]] = []
    hard_ids = list(LINTS)

    async def status(text: str) -> None:
        if on_status:
            await on_status(text)

    for attempt in range(total):
        await status(STAGE_GENERATE if attempt == 0 else stage_repair(len(last_errors), attempt + 1, total))
        async with tracer.tool("generate_a2ui", {"attempt": attempt + 1, "of": total}) as call:
            try:
                res = await generate(system_prompt(), prompt_for_model)
            except ValueError as err:
                # Empty, truncated or non-JSON reply: a failed attempt to retry, not a crashed turn.
                last_errors = [f"The previous reply was not a usable A2UI JSON object: {err}"]
                call.set(f"no usable JSON: {err}", errors=last_errors)
                if log:
                    log.warn(f"UI attempt {attempt + 1}/{total} unusable — {err}")
                continue
            doc = last_doc = res["json"]

            # Auto-repair orphans/root wiring first (mutates doc), then hard-gate on catalog.json.
            graph_validation = validate_and_repair_graph(doc)
            schema_validation = validate_a2ui_document(doc)
            errors = collect_errors(graph_validation, schema_validation)
            call.set(
                "passed the schema gate" if not errors else f"schema gate rejected it: {len(errors)} error(s)",
                errors=errors, components=schema_validation["checked"],
            )

        # Hard rules: deterministic lints, same treatment as schema errors.
        if not errors:
            async with tracer.tool("guidelines.lint", {"rules": hard_ids}) as call:
                lint_lines, violations = lint_messages(doc)
                ids = sorted({v.rule_id for v in violations})
                call.set(f"{len(violations)} violation(s): {', '.join(ids)}" if violations else "all hard rules pass",
                         violations=lint_lines)
            errors = lint_lines

        # Soft rules: the judge, against the rules GROUND retrieved for this request.
        if not errors and judge and soft_rules:
            await status(STAGE_JUDGE)
            async with tracer.tool("guidelines.judge", {"rules": [r.id for r in soft_rules]}) as call:
                found = await judge(doc, soft_rules, user_prompt)
                call.set(f"{len(found)} issue(s): {', '.join(v.ruleId for v in found)}" if found else "follows the guidelines",
                         violations=[v.model_dump() for v in found])
            if found and repair_soft and attempt < max_repairs:
                errors = [violation_message(v, soft_rules) for v in found]
            else:
                # Out of repairs: ship the valid UI, flag what the judge still sees.
                flags = [v.model_dump() for v in found]

        if not errors:
            if log:
                repaired = " (graph auto-repaired)" if graph_validation["repaired"] else ""
                flagged = f", {len(flags)} guideline flag(s)" if flags else ""
                log.step(f"UI valid on attempt {attempt + 1}/{total}{repaired}{flagged}")
            return {
                "ok": True,
                "a2ui": doc,
                "attempts": attempt + 1,
                "meta": {
                    "provider": res["provider"],
                    "model": res["model"],
                    "attempts": attempt + 1,
                    "graphRepaired": graph_validation["repaired"],
                    "schemaChecked": schema_validation["checked"],
                    "unknownComponents": schema_validation["unknownComponents"],
                    "guidelines": {
                        "hardRules": hard_ids,
                        "softRules": [r.id for r in soft_rules] if judge else [],
                        "flags": flags,
                    },
                },
            }

        last_errors = errors
        if log:
            log.warn(f"UI attempt {attempt + 1}/{total} rejected — {len(errors)} error(s): {' | '.join(errors)}")
        if attempt < max_repairs:
            prompt_for_model = build_repair_prompt(request, doc, errors)

    return {"ok": False, "errors": last_errors, "attempts": total, "last_doc": last_doc}
