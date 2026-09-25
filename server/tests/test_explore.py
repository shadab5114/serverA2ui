"""P8 explorer: patches, the data contract, and ADAPT -> REFINE turns through the real graph (fake models)."""

from __future__ import annotations

import copy
import json

import httpx
import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langgraph.checkpoint.memory import InMemorySaver

from app.config import settings
from app.data.providers import get_provider
from app.explore.lineage import baseline_record, label, next_id, rebuild, screen_lines
from app.explore.patching import PatchError, apply_patch, describe_patch, item_labels, list_items, to_view
from app.explore.variants import Screen, check, data_contract_errors, parse_proposals, schema_subset
from app.graph.playground import build_graph
from app.main import app
from app.templates.render import component_scopes, render_template
from app.templates.store import FileTemplateStore
from app.verify.judge import SoftViolation

from .test_contract import decide_says, fake_grounder, parse_frames, tool_calls
from .test_verify import fake_rag

STORE = FileTemplateStore(settings.templates_dir)


def plan_tiles() -> Screen:
    doc = render_template(STORE.get("plan-tiles"), {})["a2ui"]
    return Screen(doc, get_provider("plans.list"), "plan-tiles@1")


HOTSPOT = [
    {"op": "add", "path": "/components/plan-hotspot",
     "value": {"component": "Text", "kind": "body", "size": "small", "children": {"path": "hotspotLabel"}}},
    {"op": "add", "path": "/components/plan-body/children/1", "value": "plan-hotspot"},
]
RETITLE = [{"op": "replace", "path": "/components/heading/children", "value": "Compare plans"}]
COVERAGE = [  # binds to data plans.list doesn't have
    {"op": "add", "path": "/components/plan-coverage",
     "value": {"component": "Text", "kind": "body", "size": "small", "children": {"path": "coverage"}}},
    {"op": "add", "path": "/components/plan-body/children/-", "value": "plan-coverage"},
]


# --- patching ---------------------------------------------------------------------

def test_view_round_trip_and_patch_leave_the_rest_byte_identical():
    screen = plan_tiles()
    before = copy.deepcopy(screen.doc)
    out = apply_patch(screen.doc, HOTSPOT)
    assert screen.doc == before  # the baseline isn't mutated
    old, new = to_view(before)["components"], to_view(out)["components"]
    assert set(new) - set(old) == {"plan-hotspot"}
    assert new["plan-body"]["children"] == ["plan-data", "plan-hotspot", "plan-features", "plan-choose"]
    assert {k: v for k, v in new.items() if k not in ("plan-hotspot", "plan-body")} == {
        k: v for k, v in old.items() if k != "plan-body"}
    data = [m for m in out["a2ui"] if "updateDataModel" in m]
    assert data == [m for m in before["a2ui"] if "updateDataModel" in m]


@pytest.mark.parametrize("patch, why", [
    ([], "non-empty list"),
    ([{"op": "replace", "path": "/data/x", "value": 1}], "outside /components/"),
    ([{"op": "add", "path": "/components/x"}], "has no value"),
    ([{"op": "remove", "path": "/components/nope"}], "doesn't apply"),
    ([{"op": "add", "path": "/components/x", "value": {"kind": "body"}}], 'needs a "component"'),
])
def test_bad_patches_are_rejected_with_a_reason(patch, why):
    with pytest.raises(PatchError, match=why):
        apply_patch(plan_tiles().doc, patch)


def test_describe_patch():
    assert describe_patch(HOTSPOT) == ["added plan-hotspot (Text)", "plan-body.children.1: added → \"plan-hotspot\""]
    assert describe_patch(RETITLE) == ['heading.children: changed → "Compare plans"']


def test_describe_patch_marks_static_changes_that_hit_every_list_item():
    red = [{"op": "replace", "path": "/components/plan-tile/cap/backgroundColor", "value": "red"}]
    scopes = component_scopes(plan_tiles().doc)
    assert describe_patch(red, scopes) == ['plan-tile.cap.backgroundColor: changed → "red" (applies to every item in /plans)']
    assert describe_patch(RETITLE, scopes) == ['heading.children: changed → "Compare plans"']  # top level: one item
    bound = [{"op": "replace", "path": "/components/plan-data/children", "value": {"path": "hotspotLabel"}}]
    assert describe_patch(bound, scopes) == ["plan-data.children: changed"]  # per-item data, not one static value


# --- verify -----------------------------------------------------------------------

def test_valid_variant_passes_every_check():
    doc, errors, schema, _ = check(plan_tiles(), HOTSPOT)
    assert errors == [] and doc is not None and schema["checked"] > 0


def test_data_contract_rejects_bindings_the_provider_doesnt_have():
    screen = plan_tiles()
    _, errors, _, _ = check(screen, COVERAGE)
    assert len(errors) == 1 and "/plans/*/coverage" in errors[0] and "missingData" in errors[0]
    assert data_contract_errors(screen.doc, screen.provider) == []


def test_hard_rules_apply_to_variants():
    primary = [{"op": "replace", "path": "/components/plan-choose/kind", "value": "primary"}]
    _, errors, _, _ = check(plan_tiles(), primary)
    assert any("DS-101" in e for e in errors)


def test_a_variant_for_some_items_cant_restyle_every_item():
    red = [{"op": "replace", "path": "/components/plan-tile/cap/backgroundColor", "value": "red"}]
    _, errors, _, _ = check(plan_tiles(), red, "some")
    assert len(errors) == 1 and "applies to every item alike" in errors[0] and '"unroll"' in errors[0]
    assert check(plan_tiles(), red, "all")[1] == []  # "make every cap red" is fine
    assert check(plan_tiles(), RETITLE, "some")[1] == []  # a top-level change isn't per item


RED_BEST_VALUE = [  # item 2 of the unfiltered plans is "Unlimited Go", badged "Best value"
    {"op": "unroll", "path": "/components/plan-row"},
    {"op": "replace", "path": "/components/plan-tile-2/cap/backgroundColor", "value": "red"},
]


def test_unroll_lets_one_item_differ():
    screen = plan_tiles()
    doc, errors, _, _ = check(screen, RED_BEST_VALUE, "some")
    assert errors == []  # gate, lints, data contract and targeting all pass
    comps = to_view(doc)["components"]
    n = len(get_provider("plans.list").call({})["plans"])
    assert comps["plan-row"]["children"] == [f"plan-tile-{i}" for i in range(n)]
    assert "plan-tile" not in comps and "plan-body" not in comps  # the template's item components are replaced
    assert comps["plan-feature"]["children"] == {"path": "text"}  # nested list items stay templates
    assert comps["plan-features-2"]["children"] == {"path": "/plans/2/features", "componentId": "plan-feature"}
    assert comps["plan-tile-2"]["header"]["title"]["children"] == {"path": "/plans/2/name"}
    assert comps["plan-choose-2"]["action"]["event"]["context"]["planId"] == {"path": "/plans/2/id"}
    assert [comps[f"plan-tile-{i}"]["cap"]["backgroundColor"] for i in range(n)].count("red") == 1
    data = [m for m in doc["a2ui"] if "updateDataModel" in m][0]["updateDataModel"]["value"]
    assert data["plans"][2]["badge"] == "Best value"


def test_unroll_is_described_and_named_by_item():
    doc, _, _, _ = check(plan_tiles(), RED_BEST_VALUE, "some")
    assert describe_patch(RED_BEST_VALUE, component_scopes(doc), item_labels(doc)) == [
        "plan-row: split into one copy per item (fixed to the items shown now)",
        'plan-tile-2 (Unlimited Go).cap.backgroundColor: changed → "red"',
    ]


def test_unroll_errors_and_lists_for_the_prompt():
    with pytest.raises(PatchError, match="isn't a list"):
        apply_patch(plan_tiles().doc, [{"op": "unroll", "path": "/components/heading"}])
    with pytest.raises(PatchError, match="inside another list item"):
        apply_patch(plan_tiles().doc, [{"op": "unroll", "path": "/components/plan-features"}])
    [plans] = list_items(plan_tiles().doc)
    assert (plans["container"], plans["list"], plans["itemComponent"]) == ("plan-row", "/plans", "plan-tile")
    assert {"index": 2, "id": "unlimited-go", "name": "Unlimited Go", "badge": "Best value"}.items() <= plans["items"][2].items()


def test_an_unrolled_variant_rebuilds_and_refines_on_its_copies():
    base = baseline_record("plan-tiles", 1, {}, "Plan tiles")
    var = {**base, "kind": "variant", "patches": [RED_BEST_VALUE,
           [{"op": "replace", "path": "/components/plan-choose-2/kind", "value": "primary"}]], "title": "Red", "rationale": "r"}
    screen, _ = rebuild(var, STORE)
    comps = to_view(screen.doc)["components"]
    assert comps["plan-tile-2"]["cap"]["backgroundColor"] == "red" and comps["plan-choose-2"]["kind"] == "primary"
    assert comps["plan-choose-1"]["kind"] == "secondary"


def test_component_scopes_follow_list_templates():
    scopes = component_scopes(plan_tiles().doc)
    assert scopes["heading"] == "" and scopes["plan-tile"] == "/plans/*" and scopes["plan-feature"] == "/plans/*/features/*"


def test_schema_subset_carries_only_what_it_needs():
    sub = schema_subset(["Text", "Column", "NoSuchThing"])
    assert set(sub["components"]) == {"Text", "Column"}
    assert "ModalProps" not in sub["$defs"] and "DynamicString" in sub["$defs"]
    refs: set[str] = set()

    def walk(v):
        if isinstance(v, dict):
            if isinstance(v.get("$ref"), str) and v["$ref"].startswith("#/$defs/"):
                refs.add(v["$ref"].split("/")[-1])
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)

    walk(sub)
    assert refs <= set(sub["$defs"])  # every local $ref resolves inside the subset


def test_parse_proposals_is_tolerant_and_drops_unknown_citations():
    raw = {"variants": [{"title": "A", "rationale": "r", "sources": ["DS-203", "DS-999"], "patch": RETITLE,
                         "missingData": [{"field": "coverage", "why": "signal"}, "roaming"]}, "junk"]}
    [p] = parse_proposals(raw, {"DS-203"})
    assert p.sources == ["DS-203"] and p.missing_data == [{"field": "coverage", "why": "signal"}, {"field": "roaming", "why": ""}]
    assert parse_proposals({"title": "solo", "patch": RETITLE}, set())[0].title == "solo"


# --- lineage ----------------------------------------------------------------------

def test_lineage_ids_labels_and_rebuild():
    base = baseline_record("plan-tiles", 1, {}, "Plan tiles")
    var = {**base, "kind": "variant", "patches": [HOTSPOT, RETITLE], "title": "Hotspot", "rationale": "r"}
    surfaces = {"baseline-1": base, "var-1": var}
    assert (next_id(surfaces, "variant"), next_id(surfaces, "baseline")) == ("var-2", "baseline-2")
    assert (label("baseline-1", base), label("var-1", var)) == ("Baseline · plan-tiles@1", "Variant 1 · rev 2")
    screen, notes = rebuild(var, STORE)
    comps = to_view(screen.doc)["components"]
    assert comps["heading"]["children"] == "Compare plans" and "plan-hotspot" in comps and notes == []
    assert screen_lines(surfaces)[1].startswith('var-1 (card "Variant 1 · rev 2", a.k.a. option 1): variant "Hotspot"')


# --- through the graph --------------------------------------------------------------

def modified(ops, summary="changed it", targets="screen", **extra):
    """A fake modify reply: the screen's components from the prompt with JSON Patch `ops` applied, returned whole."""
    def reply(user):
        prompt = json.loads(user.split("\n\nYour modification was REJECTED")[0])
        view = {"components": {c["id"]: {k: v for k, v in c.items() if k != "id"} for c in prompt["components"]}}
        data = [m for m in plan_tiles().doc["a2ui"] if "updateDataModel" in m]  # the fake model "reads" data.lists
        doc = {"a2ui": [*data, {"version": "v0.9", "updateComponents": {"surfaceId": "main", "components": []}}]}
        from app.explore.patching import from_view
        out = apply_patch(from_view(doc, view), ops) if ops else from_view(doc, view)
        comps = next(m for m in out["a2ui"] if "updateComponents" in m)["updateComponents"]["components"]
        return {"summary": summary, "targets": targets, "missingData": [], "blocked": "", "components": comps, **extra}
    return reply


def variant(title, patch, sources=("DS-203",), missing=()):
    return {"title": title, "rationale": f"{title} rationale", "sources": list(sources), "missingData": list(missing), "patch": patch}


def fake_explore(*replies):
    """A fake JSON-mode call: returns the replies in order (repairs included), recording each prompt.
    A callable reply is computed from the prompt (see modified)."""
    queue = list(replies)
    seen = []

    async def generate(system, user):
        seen.append((system, user))
        reply = queue.pop(0)
        return {"json": reply(user) if callable(reply) else reply, "provider": "fake", "model": "fake-explore"}

    generate.seen = seen
    return generate


def use_explorer_graph(decide, explore, judge=None, grounder=None):
    app.state.graph = build_graph(
        InMemorySaver(), model=GenericFakeChatModel(messages=iter([])), decide=decide,
        grounder=grounder or fake_grounder(), judge=judge, explore_generate=explore,
    )
    app.state.checkpointer_kind = "memory"


def explorer_payload(text, thread="thread_x", run="run_1"):
    return {"threadId": thread, "runId": run, "messages": [{"id": "u", "role": "user", "content": text}],
            "state": {"persona": "explorer"}}


def surfaces_of(events):
    return [e["value"] for e in events if e["type"] == "CUSTOM" and e["name"] == "a2ui"]


def text_of(events):
    return "".join(e["delta"] for e in events if e["type"] == "TEXT_MESSAGE_CONTENT")


@pytest.fixture
async def client():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


class Decisions:
    """A fake DECIDE whose answer can change between turns."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.seen = []

    async def __call__(self, messages, persona, manifests, context=None):
        self.seen.append(context)
        return await self.answers.pop(0)(messages, persona, manifests, context)


async def test_adapt_emits_baseline_then_verified_variants_then_refine_changes_only_its_target(client):
    explore = fake_explore(
        {"variants": [variant("Hotspot line", HOTSPOT), variant("Coverage row", COVERAGE), variant("Retitle", RETITLE)]},
        {"variants": [variant("Coverage row", HOTSPOT, missing=[{"field": "coverage", "why": "network coverage"}])]},  # repair
        modified([{"op": "replace", "path": "/components/heading/children", "value": "Plans"}], "Shortened the title"),
    )
    decide = Decisions(decide_says("ADAPT", "plan-tiles"), decide_says("REFINE", target="var-2"))
    use_explorer_graph(decide, explore)

    r = await client.post("/agui/run", json=explorer_payload("add network coverage info to the plan view"))
    events = parse_frames(r.text)
    assert events[-1]["type"] == "RUN_FINISHED"
    shown = surfaces_of(events)
    assert [s["meta"]["card"]["label"] for s in shown] == ["Baseline · plan-tiles@1", "Variant 1", "Variant 2", "Variant 3"]
    base, *variants = shown
    assert base["meta"]["source"] == {"kind": "template", "id": "plan-tiles", "version": 1}
    assert {v["meta"]["source"]["kind"] for v in variants} == {"variant"}
    # the repaired one finishes last, so it's numbered last
    assert [v["meta"]["card"]["title"] for v in variants] == ["Hotspot line", "Retitle", "Coverage row"]
    repaired = variants[2]["meta"]
    assert repaired["attempts"] == 2 and repaired["card"]["missingData"] == [{"field": "coverage", "why": "network coverage"}]
    assert variants[0]["meta"]["card"]["changes"] == [
        "added plan-hotspot (Text)", 'plan-body.children.1: added → "plan-hotspot" (applies to every item in /plans)']
    assert variants[0]["meta"]["card"]["sources"] == [{"id": "DS-203", "title": "Consistent option tiles"}]
    caption = text_of(events)
    assert "3 variants" in caption and "Variant 3 needs data no provider has yet: `coverage`" in caption
    names = [c["name"] for c in tool_calls(events)]
    assert names[:3] == ["decide", "plans.list", "guidelines.search"] and "propose_variants" in names
    assert names.count("variant.check") == 4 and names.count("variant.repair") == 1
    # the patch prompt carries the screen, its data fields and scopes, not the whole catalog
    system, user = explore.seen[0]
    assert len(system) < 60_000 and '"relativeFields"' in user and '"hotspotLabel"' in user

    # REFINE var-2 on the same thread: one new card, the chain grows, nothing else changes.
    state = await app.state.graph.aget_state({"configurable": {"thread_id": "thread_x"}})
    before = copy.deepcopy(state.values["surfaces"])
    r = await client.post("/agui/run", json=explorer_payload("on variant 2 make the title shorter", run="run_2"))
    events = parse_frames(r.text)
    [refined] = surfaces_of(events)
    card = refined["meta"]["card"]
    assert (card["label"], card["rev"], card["changes"]) == ("Variant 2 · rev 2", 2, ['heading.children: changed → "Plans"'])
    comps = {c["id"]: c for m in refined["a2ui"] if "updateComponents" in m for c in m["updateComponents"]["components"]}
    assert comps["heading"]["children"] == "Plans"
    assert "Unchanged: Baseline · plan-tiles@1, Variant 1, Variant 3." in text_of(events)
    after = (await app.state.graph.aget_state({"configurable": {"thread_id": "thread_x"}})).values["surfaces"]
    assert after["var-2"]["patches"] == [*before["var-2"]["patches"], [
        {"op": "replace", "path": "/components/heading/children", "value": "Plans"}]]
    assert {k: v for k, v in after.items() if k != "var-2"} == {k: v for k, v in before.items() if k != "var-2"}
    # DECIDE saw what's on screen
    assert any(line.startswith('var-2 (card "Variant 2"') and '"Retitle"' in line for line in decide.seen[1].screen)
    # the refine prompt patched var-2 as it stands (rev 1 applied), not the baseline
    assert '"Compare plans"' in explore.seen[-1][1]


async def test_refining_a_baseline_starts_a_new_variant(client):
    explore = fake_explore(modified(HOTSPOT, "Added each plan's hotspot", "all"))
    use_explorer_graph(Decisions(decide_says("TEMPLATE", "plan-tiles"), decide_says("REFINE", target="baseline-1")), explore)
    r = await client.post("/agui/run", json=explorer_payload("show me the plans", thread="thread_b"))
    [base] = surfaces_of(parse_frames(r.text))
    assert base["meta"]["card"]["label"] == "Baseline · plan-tiles@1"
    r = await client.post("/agui/run", json=explorer_payload("add the hotspot to each tile", thread="thread_b", run="r2"))
    [var] = surfaces_of(parse_frames(r.text))
    assert var["meta"]["card"]["label"] == "Variant 1" and var["meta"]["source"]["base"] == "plan-tiles@1"
    surfaces = (await app.state.graph.aget_state({"configurable": {"thread_id": "thread_b"}})).values["surfaces"]
    assert surfaces["baseline-1"]["patches"] == [] and surfaces["var-1"]["from"] == "baseline-1"


async def test_explorer_flags_soft_rule_conflicts_instead_of_repairing(client):
    async def judge(doc, rules, request, change=None):
        if not change:  # the base screen is fine; the variant's change isn't
            return []
        return [SoftViolation(ruleId="DS-208", componentIds=["plan-hotspot"], problem="no reason given", fix="add one")]

    explore = fake_explore({"variants": [variant("Hotspot line", HOTSPOT)]})
    use_explorer_graph(Decisions(decide_says("ADAPT", "plan-tiles")), explore, judge=judge)
    r = await client.post("/agui/run", json=explorer_payload("add hotspot info to the plan tiles", thread="thread_f"))
    events = parse_frames(r.text)
    _, var = surfaces_of(events)
    assert var["meta"]["attempts"] == 1 and var["meta"]["card"]["flags"][0]["ruleId"] == "DS-208"
    assert len(explore.seen) == 1  # no repair call
    assert "conflicts with DS-208" in text_of(events)


async def test_findings_the_base_screen_already_has_are_not_flagged_on_variants(client):
    changes_seen = []

    async def judge(doc, rules, request, change=None):
        changes_seen.append(change)
        # e.g. every plan tile carries a badge from data: true of production, not the variant's doing
        return [SoftViolation(ruleId="DS-204", componentIds=["plan-tile"], problem="every tile is badged", fix="badge one")]

    explore = fake_explore({"variants": [variant("Retitle", RETITLE)]})
    use_explorer_graph(Decisions(decide_says("ADAPT", "plan-tiles")), explore, judge=judge)
    r = await client.post("/agui/run", json=explorer_payload("retitle the plan view", thread="thread_d"))
    events = parse_frames(r.text)
    _, var = surfaces_of(events)
    assert "flags" not in var["meta"]["card"] and "conflicts with" not in text_of(events)
    # the variant is judged on its change; the base screen without one
    assert None in changes_seen and any(c and "heading.children" in c for c in changes_seen)
    summaries = [c["result"]["summary"] for c in tool_calls(events) if c["name"] == "guidelines.judge"]
    assert any("already on the base screen" in s for s in summaries)


async def test_a_change_request_queries_the_rag_service_and_its_answer_reaches_the_prompt(client):
    seen = []
    rag = fake_rag({
        "answer": "Keep headings to one line; don't reorder the tiles.",
        "citations": [{"title": "DS-203 · Consistent option tiles", "source": "rules/tiles.md"},
                      {"title": "Headings", "text": "Headings are sentence case.", "source": "docs/headings.md"}],
    }, seen=seen)
    explore = fake_explore(modified(RETITLE, "Shortened the title"))
    use_explorer_graph(
        Decisions(decide_says("TEMPLATE", "plan-tiles"),
                  decide_says("REFINE", target="baseline-1", intent="shorten the plans heading")),
        explore, grounder=fake_grounder(sources=[rag]),
    )
    await client.post("/agui/run", json=explorer_payload("show me the plans", thread="thread_rag"))
    assert seen == []  # showing a curated screen grounds nothing

    r = await client.post("/agui/run", json=explorer_payload("make the heading shorter", thread="thread_rag", run="r2"))
    events = parse_frames(r.text)
    # The change is the query: DECIDE's intent leads, then the user's words.
    assert [c["json"] for c in seen] == [
        {"query": "shorten the plans heading. make the heading shorter", "collection_name": "design_system"}]
    # Its answer and citations are traced next to the local rules, with the endpoint that was asked...
    [call] = [c for c in tool_calls(events) if c["name"] == "guidelines.search"]
    assert call["args"]["in"] == ["guidelines.local", "guidelines.rag http://127.0.0.1:5000/query (design_system)"]
    assert {"RAG-ANSWER", "DS-203", "RAG-2"} <= {s["id"] for s in call["result"]["sources"]}
    # ...and reach the prompt the change is made from.
    guidelines = json.loads(explore.seen[-1][1])["guidelines"]
    assert {"id": "RAG-ANSWER", "title": "Guidance for this request",
            "text": "Keep headings to one line; don't reorder the tiles."} in guidelines
    assert surfaces_of(events)[0]["meta"]["card"]["label"] == "Variant 1"


async def test_a_change_request_still_works_when_the_rag_service_is_down(client):
    rag = fake_rag({"detail": "collection not found"}, status=404)
    explore = fake_explore(modified(RETITLE, "Shortened the title"))
    use_explorer_graph(
        Decisions(decide_says("TEMPLATE", "plan-tiles"),
                  decide_says("REFINE", target="baseline-1", intent="option tiles")),
        explore, grounder=fake_grounder(sources=[rag]))
    await client.post("/agui/run", json=explorer_payload("show me the plans", thread="thread_rag_down"))
    r = await client.post("/agui/run", json=explorer_payload("make the heading shorter", thread="thread_rag_down", run="r2"))
    events = parse_frames(r.text)
    [call] = [c for c in tool_calls(events) if c["name"] == "guidelines.search"]
    assert "guidelines.rag: failed" in call["result"]["note"] and call["result"]["sources"]  # local rules still there
    assert surfaces_of(events)[0]["meta"]["card"]["label"] == "Variant 1"


async def test_a_change_for_one_list_item_is_declined_not_applied_to_every_item(client):
    why = "All plan tiles are one repeated component and cap colours can't be bound to data."
    explore = fake_explore(modified([], "nothing", blocked=why))
    use_explorer_graph(Decisions(decide_says("TEMPLATE", "plan-tiles"), decide_says("REFINE", target="baseline-1")), explore)
    await client.post("/agui/run", json=explorer_payload("show me the plans", thread="thread_c"))
    r = await client.post("/agui/run", json=explorer_payload("make the best value cap red", thread="thread_c", run="r2"))
    events = parse_frames(r.text)
    assert surfaces_of(events) == []
    assert text_of(events) == f"I didn't change Baseline · plan-tiles@1: {why}"
    surfaces = (await app.state.graph.aget_state({"configurable": {"thread_id": "thread_c"}})).values["surfaces"]
    assert list(surfaces) == ["baseline-1"]


async def test_adapt_reports_a_declined_variant_next_to_the_ones_it_built(client):
    explore = fake_explore({"variants": [variant("Hotspot line", HOTSPOT),
                                         {**variant("Red cap", []), "blocked": "caps can't differ per plan"}]})
    use_explorer_graph(Decisions(decide_says("ADAPT", "plan-tiles")), explore)
    r = await client.post("/agui/run", json=explorer_payload("highlight the best value plan", thread="thread_e"))
    events = parse_frames(r.text)
    assert [s["meta"]["card"]["label"] for s in surfaces_of(events)] == ["Baseline · plan-tiles@1", "Variant 1"]
    assert "\"Red cap\" can't be done as asked: caps can't differ per plan" in text_of(events)


async def test_no_valid_variant_still_shows_the_baseline_and_says_why(client):
    # the first proposal plus every repair keeps binding to data that doesn't exist
    explore = fake_explore(*[{"variants": [variant("Coverage row", COVERAGE)]}] * (settings.max_repairs + 1))
    use_explorer_graph(Decisions(decide_says("ADAPT", "plan-tiles")), explore)
    r = await client.post("/agui/run", json=explorer_payload("add coverage", thread="thread_n"))
    events = parse_frames(r.text)
    assert [s["meta"]["card"]["label"] for s in surfaces_of(events)] == ["Baseline · plan-tiles@1"]
    assert "couldn't make any variant pass" in text_of(events)


async def test_assistant_template_turn_records_a_baseline_without_a_card(client):
    use_explorer_graph(Decisions(decide_says("TEMPLATE", "plan-tiles")), fake_explore())
    r = await client.post("/agui/run", json={**explorer_payload("show me the plans", thread="thread_a"), "state": {}})
    [surface] = surfaces_of(parse_frames(r.text))
    assert "card" not in surface["meta"]
    surfaces = (await app.state.graph.aget_state({"configurable": {"thread_id": "thread_a"}})).values["surfaces"]
    assert list(surfaces) == ["baseline-1"]
    assert json.dumps(surfaces)  # lineage is plain JSON (the checkpointer persists it)


# --- REFINE = the whole surface to the model, then check, judge, render -------------------------

async def test_the_assistant_modifies_the_ui_it_just_generated(client):
    from .test_contract import VALID_DOC, fake_generator, payload

    gen, _ = fake_generator(VALID_DOC)
    explore = fake_explore(modified([{"op": "replace", "path": "/components/submit/children", "value": "Join now"}],
                                    "Renamed the button"))
    app.state.graph = build_graph(
        InMemorySaver(), model=GenericFakeChatModel(messages=iter([])), grounder=fake_grounder(), judge=None,
        decide=Decisions(decide_says("GENERATE"), decide_says("REFINE")), generate_ui=gen, explore_generate=explore,
    )
    await client.post("/agui/run", json=payload("show me a sign-up form", thread="thread_g"))
    r = await client.post("/agui/run", json=payload("call the button Join now", thread="thread_g", run="r2"))
    events = parse_frames(r.text)
    [surface] = surfaces_of(events)
    assert surface["meta"]["source"] == {"kind": "generated", "id": "ui-1", "base": "generated UI", "rev": 2}
    assert "card" not in surface["meta"]  # the assistant gets no card chrome
    comps = {c["id"]: c for m in surface["a2ui"] if "updateComponents" in m for c in m["updateComponents"]["components"]}
    assert comps["submit"]["children"] == "Join now" and comps["email"]["label"] == "Email"
    data = [m["updateDataModel"] for m in surface["a2ui"] if "updateDataModel" in m]
    assert data == [m["updateDataModel"] for m in VALID_DOC["a2ui"] if "updateDataModel" in m]  # data re-attached as it was
    assert text_of(events) == "Generated 1 · rev 2: Renamed the button"
    decision = [c for c in tool_calls(events) if c["name"] == "decide"][0]["result"]["plan"]
    assert decision["target"] == "ui-1" and "the latest surface, ui-1" in decision["policyNotes"][0]
    # the model got the whole screen, not a patch to write
    prompt = json.loads(explore.seen[0][1])
    assert {c["id"] for c in prompt["components"]} == {"root", "email", "submit"} and prompt["change"] == "call the button Join now"
    state = (await app.state.graph.aget_state({"configurable": {"thread_id": "thread_g"}})).values
    assert state["last_surface"] == "ui-1" and state["surfaces"]["ui-1"]["patches"] == [
        [{"op": "replace", "path": "/components/submit/children", "value": "Join now"}]]


async def test_a_change_for_one_tile_that_restyles_every_tile_is_sent_back_and_fixed(client):
    every = [{"op": "replace", "path": "/components/plan-tile/cap/backgroundColor", "value": "red"}]
    explore = fake_explore(
        modified(every, "Made the Best value cap red", targets="some"),  # wrong: every tile
        modified(RED_BEST_VALUE, "Made the Best value plan's cap red", targets="some"),  # the repair splits the list
    )
    use_explorer_graph(Decisions(decide_says("TEMPLATE", "plan-tiles"), decide_says("REFINE")), explore)
    await client.post("/agui/run", json=explorer_payload("show me the plans", thread="thread_r"))
    r = await client.post("/agui/run", json=explorer_payload("make the best value cap red", thread="thread_r", run="r2"))
    events = parse_frames(r.text)
    [var] = surfaces_of(events)
    card = var["meta"]["card"]
    assert card["label"] == "Variant 1" and var["meta"]["attempts"] == 2
    # the model's own split is replayed by code, so the card shows the split and the real change, not 30 copies
    assert card["changes"] == ["plan-row: split into one copy per item (fixed to the items shown now)",
                               'plan-tile-2 (Unlimited Go).cap.backgroundColor: changed → "red"']
    comps = {c["id"]: c for m in var["a2ui"] if "updateComponents" in m for c in m["updateComponents"]["components"]}
    caps = [c["cap"]["backgroundColor"] for cid, c in comps.items() if cid.startswith("plan-tile-")]
    assert caps.count("red") == 1 and len(caps) == 5
    repair = explore.seen[1][1]
    assert "REJECTED" in repair and "applies to every item alike" in repair


async def test_a_modification_binding_to_missing_data_is_rejected(client, monkeypatch):
    explore = fake_explore(*[modified(COVERAGE, "Added coverage")] * (settings.max_repairs + 1))
    use_explorer_graph(Decisions(decide_says("TEMPLATE", "plan-tiles"), decide_says("REFINE")), explore)
    await client.post("/agui/run", json=explorer_payload("show me the plans", thread="thread_m"))
    r = await client.post("/agui/run", json=explorer_payload("add coverage", thread="thread_m", run="r2"))
    events = parse_frames(r.text)
    assert surfaces_of(events) == []
    assert "without breaking the design-system checks" in text_of(events) and "/plans/*/coverage" in text_of(events)


# --- the changes-only reply, applied by code ---------------------------------------------------

def _mod(**kw):
    from app.explore.modify import parse_modification

    return parse_modification({"summary": "s", **kw})


def test_changes_merge_props_and_leave_everything_else_alone():
    from app.explore.modify import check
    from evals.modify_cases import SETTINGS

    doc, patch, errors, _ = check(SETTINGS, _mod(update=[{"id": "save", "children": "Save changes", "kind": "secondary"}]))
    assert errors == [] and comps_of(doc)["save"]["children"] == "Save changes"
    assert comps_of(doc)["save"]["action"] == {"event": {"name": "save_settings"}}  # merged, not replaced
    assert {op["path"].split("/")[2] for op in patch} == {"save"}


def test_remove_also_drops_the_id_from_its_parent():
    from app.explore.modify import check
    from evals.modify_cases import SETTINGS

    doc, _, errors, _ = check(SETTINGS, _mod(remove=["name-field"]))
    assert errors == [] and "name-field" not in comps_of(doc) and "name-field" not in comps_of(doc)["root"]["children"]


def test_split_then_update_one_copy():
    from app.explore.modify import check
    from evals.modify_cases import ORDERS

    doc, patch, errors, _ = check(ORDERS, _mod(targets="some", split=["order-list"],
                                               update=[{"id": "order-card-1", "badge": {"children": "Late", "backgroundColor": "red"}}]))
    assert errors == [] and patch[0] == {"op": "unroll", "path": "/components/order-list"}
    assert comps_of(doc)["order-card-1"]["badge"]["backgroundColor"] == "red" and "badge" not in comps_of(doc)["order-card-0"]


def test_a_written_out_split_copy_replaces_the_code_made_one():
    from app.explore.modify import check
    from evals.modify_cases import ORDERS

    copy_1 = {"id": "order-card-1", "component": "Tilelet", "showBorder": True, "title": {"children": {"path": "/orders/1/item"}},
              "badge": {"children": "Late", "backgroundColor": "red"}}
    doc, _, errors, _ = check(ORDERS, _mod(targets="some", split=["order-list"], add=[copy_1]))
    assert errors == [] and comps_of(doc)["order-card-1"]["badge"]["children"] == "Late"


def test_changes_that_cant_apply_or_leave_strays_go_back_for_repair():
    from app.explore.modify import check
    from evals.modify_cases import SETTINGS

    assert "no component" in check(SETTINGS, _mod(update=[{"id": "nope", "x": 1}]))[2][0]
    assert "unique id" in check(SETTINGS, _mod(add=[{"id": "save", "component": "Text", "children": "x"}]))[2][0]
    stray = check(SETTINGS, _mod(add=[{"id": "hint", "component": "Text", "children": "Saved automatically"}]))[2]
    assert stray and "Not placed on the screen: hint" in stray[0]


def test_new_inputs_get_ui_state_never_content():
    from app.explore.modify import check
    from evals.modify_cases import SETTINGS

    toggle = {"id": "dark", "component": "Toggle", "ariaLabel": "Dark mode", "checked": {"path": "/form/darkMode"}}
    root = ["title", "name-field", "notify-label", "notify-toggle", "dark", "save"]
    doc, _, errors, _ = check(SETTINGS, _mod(add=[toggle], update=[{"id": "root", "children": root}], newState={"/form/darkMode": False}))
    assert errors == [] and {"path": "/form/darkMode", "surfaceId": "main", "value": False} in [
        m["updateDataModel"] for m in doc["a2ui"] if "updateDataModel" in m]
    content = check(SETTINGS, _mod(add=[toggle], update=[{"id": "root", "children": root}], newState={"/form/darkMode": "Dark"}))[2]
    assert "is content, not UI state" in content[0]
    missing = check(SETTINGS, _mod(add=[toggle], update=[{"id": "root", "children": root}]))[2]
    assert any("/form/darkMode" in e for e in missing)  # binding to state that doesn't exist


def comps_of(doc):
    return to_view(doc)["components"]
