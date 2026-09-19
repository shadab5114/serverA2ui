"""Decision evals against the REAL decide model (costs API calls, so on demand only):

    uv run pytest -m eval

Rows live in evals/decisions.jsonl:
  {prompt | action, persona, selections?, surfaces?, expect: {strategy, templateId?, params?, shows?, target?}}
`shows` ({list: [ids]}) checks the outcome instead of exact param values: the template's
provider, called with the decided params, returns exactly those items (in order).
An `action` row is a UI click ({name, context}); it runs through the same turn context
and param filling as the graph. `surfaces` is what's on screen (lineage records, P8),
the context for REFINE rows. Prompt, catalog and template changes can silently
shift decisions; this is how you notice. Grow the set whenever a decision surprises you.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from langchain_core.messages import HumanMessage

from app.agui_bridge import describe_action
from app.config import settings
from app.data.providers import REGISTRY
from app.decide.decide import make_decide, turn_context
from app.decide.policy import apply_policy, fill_params_from_selections, resolve_persona
from app.explore.lineage import screen_lines
from app.templates.store import FileTemplateStore

ROWS = [json.loads(line) for line in (Path(__file__).parent.parent / "evals" / "decisions.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]

# One loop for the module: langchain-openai caches its async HTTP client across calls.
pytestmark = [pytest.mark.eval, pytest.mark.asyncio(loop_scope="module")]


def row_id(row: dict) -> str:
    return f"{row['persona']}: " + (row.get("prompt") or f"[action] {row['action']['name']}")[:40]


@pytest.mark.parametrize("row", ROWS, ids=[row_id(r) for r in ROWS])
async def test_decision(row):
    persona = resolve_persona(row["persona"])
    every = FileTemplateStore(settings.templates_dir).manifests()
    manifests = [m for m in every if persona.name in m.personas]
    action = None
    if "action" in row:
        action = {"name": row["action"]["name"], "context": row["action"].get("context", {}),
                  "sourceComponentId": row["action"].get("sourceComponentId", ""), "surfaceId": ""}
    surfaces = row.get("surfaces") or {}
    screen = screen_lines(surfaces, row.get("latest")) if "REFINE" in persona.strategies else None
    ctx, _ = turn_context(action, row.get("selections"), every, manifests, screen)
    text = describe_action(action) if action else row["prompt"]

    decision = await make_decide()([HumanMessage(text)], persona, manifests, ctx)
    plan = apply_policy(decision, persona, manifests, on_screen=surfaces.keys(), latest=row.get("latest"))
    if plan.template_id:
        provider = REGISTRY[next(m for m in manifests if m.id == plan.template_id).provider]
        fill_params_from_selections(plan, [p.name for p in provider.params], ctx.selections)

    expect = row["expect"]
    got = f"{plan.strategy} {plan.template_id or plan.target or ''} {plan.params} ({plan.reason}) {plan.notes}"
    assert plan.strategy == expect["strategy"], got
    if "templateId" in expect:
        assert plan.template_id == expect["templateId"], got
    if "target" in expect:
        assert plan.target == expect["target"], got
    missing = set(expect.get("dataProviders", [])) - set(plan.data_providers)
    assert not missing, f"{got} dataProviders={plan.data_providers}"
    for name, value in expect.get("params", {}).items():
        assert str(plan.params.get(name, "")).lower().removeprefix("$").removesuffix(".0") == value, got
    if "shows" in expect:
        provider = REGISTRY[next(m for m in manifests if m.id == plan.template_id).provider]
        data = provider.call(plan.params)
        for key, want in expect["shows"].items():
            assert [item["id"] for item in data[key]] == want, got
