"""POLICY: every disallowed or infeasible strategy falls back predictably."""

from __future__ import annotations

import pytest

from app.decide.decide import Decision, ProviderParam, build_decide_prompt
from app.decide.policy import Persona, apply_policy, resolve_persona
from app.templates.store import Manifest


def manifest(id_: str, personas=("assistant", "explorer")) -> Manifest:
    return Manifest(id_, 1, id_.title(), "intent", [], list(personas), "plans.list", "cap", [])


MANIFESTS = [manifest("plan-tiles"), manifest("designer-only", personas=("explorer",))]


def decision(strategy: str, template_id: str | None = None, params=None, data=None, target=None) -> Decision:
    return Decision(
        intent="x", strategy=strategy, templateId=template_id,
        params=[ProviderParam(name=k, value=v) for k, v in (params or {}).items()],
        coverage="full", gaps=[], reason="r", dataProviders=data or [], target=target,
    )


ASSISTANT = resolve_persona("assistant")
EXPLORER = resolve_persona("explorer")


def test_unknown_or_missing_persona_is_assistant():
    assert resolve_persona("hacker").name == "assistant"
    assert resolve_persona(None).name == "assistant"


def test_personas_from_config():
    assert ASSISTANT.strategies == ("TEXT", "TEMPLATE", "GENERATE", "REFINE")  # modifying what's on screen is for everyone
    assert "ADAPT" in EXPLORER.strategies and EXPLORER.variants == 3


@pytest.mark.parametrize("strategy", ["TEXT", "GENERATE"])
def test_allowed_strategies_pass_through(strategy):
    plan = apply_policy(decision(strategy), ASSISTANT, MANIFESTS)
    assert plan.strategy == strategy and not plan.notes and plan.template_id is None


def test_template_keeps_id_and_params():
    plan = apply_policy(decision("TEMPLATE", "plan-tiles", {"maxPrice": "60"}), ASSISTANT, MANIFESTS)
    assert (plan.strategy, plan.template_id, plan.params, plan.notes) == ("TEMPLATE", "plan-tiles", {"maxPrice": "60"}, [])


@pytest.mark.parametrize("template_id", ["no-such-template", None, "designer-only"])
def test_unusable_template_falls_back_to_generate(template_id):
    plan = apply_policy(decision("TEMPLATE", template_id), ASSISTANT, MANIFESTS)
    assert plan.strategy == "GENERATE" and plan.template_id is None and plan.params == {}
    assert "isn't available to assistant" in plan.notes[0]


def test_explorer_may_use_an_explorer_only_template():
    plan = apply_policy(decision("TEMPLATE", "designer-only"), EXPLORER, MANIFESTS)
    assert plan.strategy == "TEMPLATE"


def test_assistant_adapt_is_not_allowed():
    plan = apply_policy(decision("ADAPT", "plan-tiles"), ASSISTANT, MANIFESTS)
    assert plan.strategy == "GENERATE" and plan.proposed == "ADAPT"
    assert plan.notes == ["ADAPT isn't allowed for assistant → GENERATE"]


def test_assistant_may_modify_what_it_showed():
    plan = apply_policy(decision("REFINE", target="ui-1"), ASSISTANT, MANIFESTS, on_screen={"ui-1"}, latest="ui-1")
    assert (plan.strategy, plan.target, plan.notes) == ("REFINE", "ui-1", [])


@pytest.mark.parametrize("target", [None, "var-9"])
def test_refine_without_a_valid_target_modifies_the_latest_surface(target):
    plan = apply_policy(decision("REFINE", target=target), EXPLORER, MANIFESTS, on_screen={"baseline-1", "ui-1"}, latest="ui-1")
    assert (plan.strategy, plan.target) == ("REFINE", "ui-1")
    assert "the latest surface, ui-1" in plan.notes[0]


def test_explorer_adapt_keeps_the_template_and_asks_for_the_persona_variants():
    plan = apply_policy(decision("ADAPT", "plan-tiles", {"maxPrice": "60"}), EXPLORER, MANIFESTS)
    assert (plan.strategy, plan.template_id, plan.params, plan.variants, plan.notes) == (
        "ADAPT", "plan-tiles", {"maxPrice": "60"}, EXPLORER.variants, [])


def test_adapt_without_a_usable_template_falls_back_to_generate():
    plan = apply_policy(decision("ADAPT", "no-such-template"), EXPLORER, MANIFESTS)
    assert plan.strategy == "GENERATE" and plan.template_id is None
    assert "isn't available to explorer" in plan.notes[0]


def test_refine_needs_its_target_on_screen():
    plan = apply_policy(decision("REFINE", target="var-2"), EXPLORER, MANIFESTS, on_screen={"baseline-1", "var-2"})
    assert (plan.strategy, plan.target, plan.template_id) == ("REFINE", "var-2", None)
    for on_screen in (set(), {"var-1"}):
        plan = apply_policy(decision("REFINE", target="var-2"), EXPLORER, MANIFESTS, on_screen=on_screen)
        assert plan.strategy == "GENERATE" and plan.target is None
        assert plan.notes == ["REFINE target 'var-2' isn't on screen → GENERATE"]


def test_only_adapt_gets_variants_and_only_refine_gets_a_target():
    for strategy in ("TEMPLATE", "GENERATE", "TEXT"):
        plan = apply_policy(decision(strategy, "plan-tiles", target="var-1"), EXPLORER, MANIFESTS, on_screen={"var-1"})
        assert (plan.variants, plan.target) == (1, None)


def test_explorer_prompt_offers_adapt_refine_and_lists_the_screen():
    from app.decide.decide import TurnContext

    prompt = build_decide_prompt(EXPLORER, MANIFESTS[:1], TurnContext(screen=("var-2: variant \"X\" of plan-tiles@1",)))
    assert "- ADAPT:" in prompt and "- REFINE:" in prompt and "choose ADAPT with that template" in prompt
    assert "Surfaces on screen" in prompt and "var-2: variant" in prompt
    assert "Surfaces on screen" not in build_decide_prompt(EXPLORER, MANIFESTS[:1], TurnContext())


def test_text_is_the_last_resort():
    text_only = Persona("kiosk", "", ("TEXT",), 1, "repair", False)
    for strategy in ("TEMPLATE", "ADAPT", "GENERATE", "REFINE"):
        assert apply_policy(decision(strategy, "plan-tiles"), text_only, MANIFESTS).strategy == "TEXT"


def test_decide_prompt_offers_only_what_the_persona_may_do():
    prompt = build_decide_prompt(ASSISTANT, MANIFESTS[:1])
    assert "- TEMPLATE:" in prompt and "- GENERATE:" in prompt and "- REFINE:" in prompt
    assert "- ADAPT:" not in prompt and "choose ADAPT" not in prompt
    assert "plan-tiles" in prompt and "maxPrice (number, optional)" in prompt
