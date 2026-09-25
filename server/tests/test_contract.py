"""Wire-contract checks: event order, frame shape and headers the React client depends on.

The graph runs with a fake streaming model and an in-memory checkpointer, so
these need neither OpenAI nor Postgres.
"""

from __future__ import annotations

import copy
import functools
import json

import httpx
import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver

from app.config import settings
from app.decide.decide import Decision, ProviderParam
from app.generation.generate import generate_validated_a2ui
from app.ground.ground import BriefRule, DesignBrief, Grounder
from app.grounding.sources import Guidelines, LocalGuidelines
from app.graph.playground import build_graph
from app.main import app
from app.templates.store import FileTemplateStore


class RecordingFakeModel(GenericFakeChatModel):
    """Fake streaming model that also records the prompts it was given."""

    seen: list = []

    async def _astream(self, messages, *args, **kwargs):
        self.seen.append(messages)
        async for chunk in super()._astream(messages, *args, **kwargs):
            yield chunk


class BrokenModel(GenericFakeChatModel):
    async def _astream(self, *args, **kwargs):
        raise RuntimeError("model exploded")
        yield  # pragma: no cover


def parse_frames(body: str) -> list[dict]:
    """Split the way client/src/Chat.tsx does: on blank lines, payload on the `data:` line."""
    events = []
    for chunk in body.split("\n\n"):
        if not chunk:
            continue
        lines = chunk.split("\n")
        assert len(lines) == 1 and lines[0].startswith("data: "), f"bad frame: {chunk!r}"
        events.append(json.loads(lines[0][len("data: "):]))
    return events


def decide_says(strategy: str = "TEXT", template_id: str | None = None, params: dict | None = None, data=None,
                target=None, intent="test"):
    """A fake DECIDE that always proposes the same thing (records what it was shown)."""
    seen: list = []

    async def decide(messages, persona, manifests, context=None):
        seen.append((list(messages), persona, manifests, context))
        return Decision(
            intent=intent, strategy=strategy, templateId=template_id,
            params=[ProviderParam(name=k, value=str(v)) for k, v in (params or {}).items()],
            coverage="full" if template_id else "none", gaps=[], reason="because the test says so",
            dataProviders=data or [], target=target,
        )

    decide.seen = seen
    return decide


def statuses(events: list[dict]) -> list[str]:
    return [e["value"]["text"] for e in events if e["type"] == "CUSTOM" and e["name"] == "status"]


TRACE_TYPES = {"STEP_STARTED", "STEP_FINISHED", "TOOL_CALL_START", "TOOL_CALL_ARGS", "TOOL_CALL_END", "TOOL_CALL_RESULT"}


def without_status(events: list[dict]) -> list[dict]:
    """The core contract: everything except progress (status) and trace (steps, tool calls) events."""
    return [e for e in events if not (e["type"] == "CUSTOM" and e["name"] == "status") and e["type"] not in TRACE_TYPES]


def tool_calls(events: list[dict]) -> list[dict]:
    """Traced tool calls as {name, args, result}, in order."""
    by_id: dict[str, dict] = {}
    for e in events:
        if e["type"] == "TOOL_CALL_START":
            by_id[e["toolCallId"]] = {"name": e["toolCallName"]}
        elif e["type"] == "TOOL_CALL_ARGS":
            by_id[e["toolCallId"]]["args"] = json.loads(e["delta"])
        elif e["type"] == "TOOL_CALL_RESULT":
            by_id[e["toolCallId"]]["result"] = json.loads(e["content"])
    return list(by_id.values())


FAKE_BRIEF = DesignBrief(
    pattern="PAT-302", patternWhy="it's a form", components=["Column", "InputField", "Button"],
    layout="A column with the fields, then one primary submit button.",
    rules=[BriefRule(id="DS-102", how="label every field"), BriefRule(id="DS-206", how="submit last")],
    dataUse="no data",
)


def fake_grounder(brief: DesignBrief = FAKE_BRIEF, sources: list | None = None) -> Grounder:
    """Real grounding over the local guideline markdown; the brief model and MCP are stubbed.
    `sources` adds guideline sources next to it (e.g. a canned RAG service)."""
    seen: list = []

    async def make_brief(system, inputs):
        seen.append(inputs)
        return brief

    g = Grounder(guidelines=Guidelines([LocalGuidelines(), *(sources or [])]), mcp=None, brief=make_brief)
    g.seen = seen
    return g


def use_graph(model=None, decide=None, generate_ui=None, grounder=None, judge=None) -> InMemorySaver:
    saver = InMemorySaver()
    kwargs = {"generate_ui": generate_ui} if generate_ui else {}
    app.state.graph = build_graph(
        saver,
        model=model or GenericFakeChatModel(messages=iter([])),
        decide=decide or decide_says("TEXT"),
        grounder=grounder or fake_grounder(),
        judge=judge,
        **kwargs,
    )
    app.state.checkpointer_kind = "memory"
    return saver


def payload(text: str, thread: str = "thread_abc", run: str = "run_1") -> dict:
    return {"threadId": thread, "runId": run, "messages": [{"id": "u_1", "role": "user", "content": text}]}


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_health(client):
    use_graph()
    r = await client.get("/agui/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "phase": 8, "endpoint": "/agui/run", "checkpointer": "memory"}


async def test_text_turn_contract(client):
    use_graph(GenericFakeChatModel(messages=iter([AIMessage("Hello there, friend")])))
    r = await client.post("/agui/run", json=payload("hi"))
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    assert r.headers["cache-control"] == "no-cache, no-transform"
    assert r.headers["x-accel-buffering"] == "no"

    all_events = parse_frames(r.text)
    assert statuses(all_events) == ["Reading your request…"]  # progress while DECIDE runs
    events = without_status(all_events)
    types = [e["type"] for e in events]
    assert types[0] == "RUN_STARTED"
    assert types[1] == "TEXT_MESSAGE_START"
    assert set(types[2:-2]) == {"TEXT_MESSAGE_CONTENT"} and len(types) > 5  # really streamed
    assert types[-2:] == ["TEXT_MESSAGE_END", "RUN_FINISHED"]

    assert (events[0]["threadId"], events[0]["runId"]) == ("thread_abc", "run_1")
    assert (events[-1]["threadId"], events[-1]["runId"]) == ("thread_abc", "run_1")
    assert events[1]["role"] == "assistant"
    msg_id = events[1]["messageId"]
    assert all(e["messageId"] == msg_id for e in events[1:-1])
    assert "".join(e["delta"] for e in events if e["type"] == "TEXT_MESSAGE_CONTENT") == "Hello there, friend"
    for e in events:  # camelCase only, nothing null
        assert "_" not in "".join(e.keys())
        assert None not in e.values()


async def test_memory_by_thread(client):
    model = RecordingFakeModel(messages=iter([AIMessage("Nice to meet you"), AIMessage("You are Ada"), AIMessage("?")]))
    model.seen.clear()
    use_graph(model)

    await client.post("/agui/run", json=payload("my name is Ada", thread="thread_mem"))
    await client.post("/agui/run", json=payload("what is my name?", thread="thread_mem", run="run_2"))
    await client.post("/agui/run", json=payload("what is my name?", thread="thread_other", run="run_3"))

    # second turn on the same thread sees the whole history; another thread sees none
    same, other = model.seen[1], model.seen[2]
    assert [m.content for m in same[1:]] == ["my name is Ada", "Nice to meet you", "what is my name?"]
    assert [m.content for m in other[1:]] == ["what is my name?"]
    stored = await app.state.graph.aget_state({"configurable": {"thread_id": "thread_mem"}})
    assert len(stored.values["messages"]) == 4


async def test_run_error(client):
    use_graph(BrokenModel(messages=iter([])))
    r = await client.post("/agui/run", json=payload("hi"))
    events = parse_frames(r.text)
    assert events[0]["type"] == "RUN_STARTED"
    assert events[-1] == {**events[-1], "type": "RUN_ERROR", "message": "model exploded"}
    assert "RUN_FINISHED" not in [e["type"] for e in events]


async def test_lenient_input_generates_ids(client):
    use_graph(GenericFakeChatModel(messages=iter([AIMessage("ok")])))
    r = await client.post("/agui/run", json={"messages": []})
    assert r.status_code == 200
    first = parse_frames(r.text)[0]
    assert first["threadId"].startswith("thread_")
    assert first["runId"].startswith("run_")


# --- UI branch (real gate + repair loop, fake LLM) ---------------------------

VALID_DOC = {
    "a2ui": [
        {"version": "v0.9", "createSurface": {"surfaceId": "main", "catalogId": "x"}},
        {"version": "v0.9", "updateDataModel": {"surfaceId": "main", "path": "/", "value": {"form": {"email": ""}}}},
        {"version": "v0.9", "updateComponents": {"surfaceId": "main", "components": [
            {"id": "root", "component": "Column", "children": ["email", "submit"]},
            {"id": "email", "component": "InputField", "label": "Email", "value": {"path": "/form/email"}},
            {"id": "submit", "component": "Button", "children": "Sign up"},
        ]}},
    ]
}


def invalid_doc() -> dict:
    doc = copy.deepcopy(VALID_DOC)
    doc["a2ui"][2]["updateComponents"]["components"][2]["kind"] = "tertiary"
    return doc


def fake_generator(*docs):
    """generate_ui backed by the real gate/repair loop, with the LLM replaced by canned docs."""
    queue = [copy.deepcopy(d) for d in docs]
    prompts: list[str] = []

    async def generate(system_prompt: str, user_prompt: str):
        prompts.append(user_prompt)
        return {"json": queue.pop(0), "provider": "fake", "model": "fake-1"}

    return functools.partial(generate_validated_a2ui, generate=generate), prompts


def text_messages(events: list[dict]) -> list[str]:
    return ["".join(e["delta"] for e in events if e["type"] == "TEXT_MESSAGE_CONTENT" and e["messageId"] == mid)
            for mid in dict.fromkeys(e["messageId"] for e in events if e["type"] == "TEXT_MESSAGE_START")]


async def test_ui_turn_contract(client):
    gen, _ = fake_generator(VALID_DOC)
    use_graph(decide=decide_says("GENERATE"), generate_ui=gen)
    events = parse_frames((await client.post("/agui/run", json=payload("show me a sign-up form"))).text)

    assert [e["type"] for e in without_status(events)] == [
        "RUN_STARTED", "CUSTOM",
        "TEXT_MESSAGE_START", "TEXT_MESSAGE_CONTENT", "TEXT_MESSAGE_END", "RUN_FINISHED",
    ]
    assert statuses(events) == [
        "Reading your request…",
        "Grounding the UI in the design guidelines…",
        "Generating UI from the design system's components…",
    ]
    surface = next(e for e in events if e["type"] == "CUSTOM" and e["name"] == "a2ui")
    assert surface["value"]["a2ui"] == VALID_DOC["a2ui"]
    meta = surface["value"]["meta"]
    assert {k: meta[k] for k in ("provider", "model", "attempts", "graphRepaired", "schemaChecked", "unknownComponents")} == {
        "provider": "fake", "model": "fake-1", "attempts": 1, "graphRepaired": False,
        "schemaChecked": 2, "unknownComponents": ["Column"],
    }
    assert meta["source"] == {"kind": "generated", "id": "ui-1", "rev": 1}  # recorded, so it can be modified later
    assert meta["decision"]["strategy"] == "GENERATE" and meta["decision"]["persona"] == "assistant"
    assert text_messages(events) == ["Here's the UI you asked for."]


async def test_ui_turn_repairs_then_succeeds(client):
    gen, prompts = fake_generator(invalid_doc(), VALID_DOC)
    use_graph(decide=decide_says("GENERATE"), generate_ui=gen)
    events = parse_frames((await client.post("/agui/run", json=payload("sign-up form"))).text)

    surface = next(e for e in events if e["type"] == "CUSTOM" and e["name"] == "a2ui")
    assert surface["value"]["meta"]["attempts"] == 2
    assert statuses(events)[-1] == "Fixing 1 issue the design-system check found (attempt 2 of 3)…"
    # The generator gets the request plus GROUND's brief; a repair keeps both.
    assert prompts[0].startswith("sign-up form\n\nDesign brief (follow it):\n- Pattern: PAT-302")
    assert prompts[1].startswith(prompts[0] + "\n\nYour previous A2UI JSON was REJECTED")
    assert 'Component "submit" (Button): kind: ' in prompts[1]


async def test_gate_failure_turn_apologises(client):
    gen, prompts = fake_generator(invalid_doc(), invalid_doc(), invalid_doc())
    use_graph(decide=decide_says("GENERATE"), generate_ui=gen)
    events = parse_frames((await client.post("/agui/run", json=payload("sign-up form"))).text)

    assert [e["type"] for e in without_status(events)] == [
        "RUN_STARTED", "TEXT_MESSAGE_START", "TEXT_MESSAGE_CONTENT", "TEXT_MESSAGE_END", "RUN_FINISHED",
    ]  # no a2ui event
    assert statuses(events) == [
        "Reading your request…",
        "Grounding the UI in the design guidelines…",
        "Generating UI from the design system's components…",
        "Fixing 1 issue the design-system check found (attempt 2 of 3)…",
        "Fixing 1 issue the design-system check found (attempt 3 of 3)…",
    ]
    assert text_messages(events) == [
        "I couldn't build a valid UI for that. Could you rephrase or simplify the request? "
        "(The generated layout didn't pass validation.)"
    ]
    assert len(prompts) == 3  # 1 + A2UI_MAX_REPAIRS (2)


async def test_ui_turn_is_recorded_compactly_in_history(client):
    gen, _ = fake_generator(VALID_DOC)
    use_graph(decide=decide_says("GENERATE"), generate_ui=gen)
    await client.post("/agui/run", json=payload("sign-up form", thread="thread_ui"))
    stored = await app.state.graph.aget_state({"configurable": {"thread_id": "thread_ui"}})
    assert [m.content for m in stored.values["messages"]] == ["sign-up form", "Here's the UI you asked for."]


async def broken_decide(messages, persona, manifests, context=None):
    raise RuntimeError("decide down")


async def test_decide_error_falls_back_to_text(client):
    use_graph(model=GenericFakeChatModel(messages=iter([AIMessage("plain answer")])),
              decide=broken_decide)
    events = parse_frames((await client.post("/agui/run", json=payload("anything"))).text)
    assert text_messages(events) == ["plain answer"]
    assert events[-1]["type"] == "RUN_FINISHED"


async def test_slow_generation_ticks_elapsed_seconds(client, monkeypatch):
    import asyncio

    from app.graph import progress

    monkeypatch.setattr(progress, "TICK_SECONDS", 0.05)
    clock = iter(range(0, 1000))
    monkeypatch.setattr(progress, "_now", lambda: float(next(clock)))  # 1 "second" per read

    async def slow_generate(system_prompt, user_prompt):
        await asyncio.sleep(0.2)
        return {"json": copy.deepcopy(VALID_DOC), "provider": "fake", "model": "fake-1"}

    use_graph(decide=decide_says("GENERATE"),
              generate_ui=functools.partial(generate_validated_a2ui, generate=slow_generate))
    events = parse_frames((await client.post("/agui/run", json=payload("sign-up form"))).text)
    ticks = [s for s in statuses(events) if s.startswith("Generating UI") and s.endswith("s")]
    assert len(ticks) >= 2, statuses(events)
    assert all(s[:-1].rsplit(" ", 1)[1].isdigit() for s in ticks)
    assert any(e["type"] == "CUSTOM" and e["name"] == "a2ui" for e in events)


# --- TEMPLATE branch (P5) -----------------------------------------------------

async def test_template_turn_renders_curated_surface_with_filtered_data(client):
    decide = decide_says("TEMPLATE", "plan-tiles", {"maxPrice": "60", "unlimitedOnly": "true"})
    use_graph(decide=decide)
    body = payload("unlimited plans under $60") | {"state": {"persona": "assistant"}}
    events = parse_frames((await client.post("/agui/run", json=body)).text)

    assert [e["type"] for e in without_status(events)] == [
        "RUN_STARTED", "CUSTOM", "TEXT_MESSAGE_START", "TEXT_MESSAGE_CONTENT", "TEXT_MESSAGE_END", "RUN_FINISHED",
    ]
    assert statuses(events) == ["Reading your request…", "Loading the plan tiles screen…"]
    surface = next(e for e in events if e["type"] == "CUSTOM" and e["name"] == "a2ui")["value"]
    data = next(m["updateDataModel"]["value"] for m in surface["a2ui"] if "updateDataModel" in m)
    assert [p["id"] for p in data["plans"]] == ["unlimited-go"]
    assert surface["meta"]["source"] == {"kind": "template", "id": "plan-tiles", "version": 1}
    assert surface["meta"]["decision"]["params"] == {"maxPrice": "60", "unlimitedOnly": "true"}
    assert text_messages(events) == ["Here are the plans."]
    _, persona, manifests, _ = decide.seen[0]
    assistant_templates = {m.id for m in FileTemplateStore(settings.templates_dir).manifests() if "assistant" in m.personas}
    assert persona.name == "assistant" and {m.id for m in manifests} == assistant_templates >= {"plan-tiles", "plan-addons"}


async def test_template_turn_is_identical_across_runs(client):
    surfaces = []
    for i in range(2):
        use_graph(decide=decide_says("TEMPLATE", "plan-tiles"))
        events = parse_frames((await client.post("/agui/run", json=payload("show me the plans", thread=f"t{i}"))).text)
        surfaces.append(next(e for e in events if e["type"] == "CUSTOM" and e["name"] == "a2ui")["value"]["a2ui"])
    assert surfaces[0] == surfaces[1]


async def test_bad_provider_param_still_renders_the_screen(client):
    use_graph(decide=decide_says("TEMPLATE", "plan-addons", {"planId": "no-such-plan"}))
    events = parse_frames((await client.post("/agui/run", json=payload("add-ons for the gold plan"))).text)
    surface = next(e for e in events if e["type"] == "CUSTOM" and e["name"] == "a2ui")["value"]
    data = next(m["updateDataModel"]["value"] for m in surface["a2ui"] if "updateDataModel" in m)
    assert data["heading"] == "Add-ons"  # rendered without the rejected param


async def test_unknown_template_falls_back_to_generate(client):
    gen, _ = fake_generator(VALID_DOC)
    use_graph(decide=decide_says("TEMPLATE", "no-such-template"), generate_ui=gen)
    events = parse_frames((await client.post("/agui/run", json=payload("show me something"))).text)
    surface = next(e for e in events if e["type"] == "CUSTOM" and e["name"] == "a2ui")["value"]
    assert surface["meta"]["source"]["kind"] == "generated"
    assert "no-such-template" in surface["meta"]["decision"]["policyNotes"][0]


# --- UI actions (P6) ------------------------------------------------------------

def action_payload(name: str, context: dict, thread: str = "thread_act", source: str = "plan-choose") -> dict:
    """What the client sends when a component fires an event: an A2UI v0.9 client action in forwardedProps."""
    return {
        "threadId": thread, "runId": "run_a", "messages": [],
        "forwardedProps": {"a2uiAction": {"version": "v0.9", "action": {
            "name": name, "surfaceId": "surface_x", "sourceComponentId": source,
            "timestamp": "2026-09-19T08:00:00.000Z", "context": context,
        }}},
    }


def test_parse_action_envelope_and_bare_forms():
    from app.agui_bridge import parse_run_input

    req = parse_run_input(action_payload("select_plan", {"planId": "unlimited-plus"}))
    assert req.action == {"name": "select_plan", "context": {"planId": "unlimited-plus"},
                          "sourceComponentId": "plan-choose", "surfaceId": "surface_x"}
    assert req.user_text == '[UI action] select_plan on "plan-choose" {"planId": "unlimited-plus"}'
    bare = parse_run_input({"forwardedProps": {"a2uiAction": {"name": "go", "context": {}}}})
    assert bare.action["name"] == "go"
    for junk in ({}, {"forwardedProps": {"a2uiAction": {"action": {"context": {}}}}}, {"forwardedProps": "x"}):
        assert parse_run_input(junk).action is None


async def test_choose_a_plan_shows_its_addons(client):
    # DECIDE picks the add-ons screen but leaves planId out: it must come from the click, not the model.
    decide = decide_says("TEMPLATE", "plan-addons")
    use_graph(decide=decide)
    body = action_payload("select_plan", {"planId": "unlimited-plus", "planName": "Unlimited Plus"})
    events = parse_frames((await client.post("/agui/run", json=body)).text)

    assert events[0]["type"] == "RUN_STARTED" and events[-1]["type"] == "RUN_FINISHED"
    surface = next(e for e in events if e["type"] == "CUSTOM" and e["name"] == "a2ui")["value"]
    data = next(m["updateDataModel"]["value"] for m in surface["a2ui"] if "updateDataModel" in m)
    assert data["heading"] == "Add-ons for Unlimited Plus"
    assert surface["meta"]["decision"]["params"] == {"planId": "unlimited-plus"}
    assert "planId=unlimited-plus from the user's selection" in surface["meta"]["decision"]["policyNotes"]

    messages, _, _, ctx = decide.seen[0]
    assert ctx.action["name"] == "select_plan"
    assert ctx.source.id == "plan-tiles" and [m.id for m in ctx.suggested] == ["plan-addons"]
    assert messages[-1].content.startswith("[UI action] select_plan")


async def test_selections_persist_across_turns(client):
    decide = decide_says("TEXT")
    use_graph(model=GenericFakeChatModel(messages=iter([AIMessage("ok"), AIMessage("sure")])), decide=decide)
    await client.post("/agui/run", json=action_payload("select_plan", {"planId": "everyday-20", "planName": "Everyday 20"}))
    await client.post("/agui/run", json=payload("what extras can I get?", thread="thread_act", run="run_b"))

    _, _, _, ctx = decide.seen[1]
    assert ctx.action is None  # a typed turn clears the action
    assert ctx.selections == {"planId": "everyday-20", "planName": "Everyday 20"}
    stored = await app.state.graph.aget_state({"configurable": {"thread_id": "thread_act"}})
    assert stored.values["selections"]["planId"] == "everyday-20"


async def test_undeclared_event_still_reaches_decide(client):
    decide = decide_says("TEXT")
    use_graph(model=GenericFakeChatModel(messages=iter([AIMessage("Thanks for signing up!")])), decide=decide)
    events = parse_frames((await client.post("/agui/run", json=action_payload(
        "submit_login", {"email": "a@b.c"}, source="submit"))).text)
    assert text_messages(events) == ["Thanks for signing up!"]
    _, _, _, ctx = decide.seen[0]
    assert ctx.source is None and ctx.selections == {"email": "a@b.c"}


# --- grounding, guideline gate and trace (P7) -------------------------------------

def rule_breaking_doc() -> dict:
    """Schema-valid, but breaks hard rules DS-101 (two primary buttons) and DS-105 (literal price)."""
    doc = copy.deepcopy(VALID_DOC)
    comps = doc["a2ui"][2]["updateComponents"]["components"]
    comps[0]["children"] = ["email", "submit", "price", "send"]
    comps.append({"id": "send", "component": "Button", "children": "Send"})
    comps.append({"id": "price", "component": "Text", "children": "Only $99/mo"})
    return doc


async def test_trace_shows_decision_grounding_brief_and_checks(client):
    gen, _ = fake_generator(VALID_DOC)
    use_graph(decide=decide_says("GENERATE"), generate_ui=gen)
    events = parse_frames((await client.post("/agui/run", json=payload("a sign-up form with email"))).text)

    steps = [(e["type"], e["stepName"]) for e in events if e["type"].startswith("STEP_")]
    assert steps == [
        ("STEP_STARTED", "decide"), ("STEP_FINISHED", "decide"),
        ("STEP_STARTED", "ground"), ("STEP_FINISHED", "ground"),
        ("STEP_STARTED", "build"), ("STEP_FINISHED", "build"),
    ]
    calls = tool_calls(events)
    assert [c["name"] for c in calls] == ["decide", "guidelines.search", "design_brief", "generate_a2ui", "guidelines.lint"]
    decide, search, brief, _, lint = calls
    assert decide["result"]["summary"] == "GENERATE: because the test says so"
    assert any(s["id"] == "PAT-302" for s in search["result"]["sources"])  # "sign-up form" finds the form pattern
    assert brief["result"]["brief"]["pattern"] == "PAT-302"
    assert lint["result"]["summary"] == "all hard rules pass"
    for c in calls:  # every traced call has its args and a result
        assert {"name", "args", "result"} <= set(c)

    meta = next(e for e in events if e["type"] == "CUSTOM" and e["name"] == "a2ui")["value"]["meta"]
    assert meta["grounding"]["brief"]["pattern"] == "PAT-302"
    assert "PAT-302" in meta["grounding"]["sources"]
    assert meta["guidelines"]["hardRules"] == ["DS-101", "DS-102", "DS-103", "DS-104", "DS-105"]


async def test_rule_breaking_ui_is_caught_by_the_guideline_gate_and_repaired(client):
    gen, prompts = fake_generator(rule_breaking_doc(), VALID_DOC)
    use_graph(decide=decide_says("GENERATE"), generate_ui=gen)
    events = parse_frames((await client.post("/agui/run", json=payload("a sign-up form, send and submit buttons, $99"))).text)

    lint_results = [c["result"] for c in tool_calls(events) if c["name"] == "guidelines.lint"]
    assert lint_results[0]["summary"] == "2 violation(s): DS-101, DS-105"
    assert lint_results[1]["summary"] == "all hard rules pass"
    assert "Guideline [DS-101 · One primary action per surface] (component submit, send)" in prompts[1]
    assert "Guideline [DS-105 · Prices come from data] (component price)" in prompts[1]
    surface = next(e for e in events if e["type"] == "CUSTOM" and e["name"] == "a2ui")["value"]
    assert surface["meta"]["attempts"] == 2


async def test_judge_flags_soft_rules_and_triggers_a_repair(client):
    from app.verify.judge import SoftViolation

    calls: list = []

    async def judge(doc, rules, request):
        calls.append([r.id for r in rules])
        if len(calls) == 1:  # cite the first rule it was given
            return [SoftViolation(ruleId=rules[0].id, componentIds=["submit"], problem="label isn't a verb", fix="say what happens")]
        return []

    gen, prompts = fake_generator(VALID_DOC, VALID_DOC)
    use_graph(decide=decide_says("GENERATE"), generate_ui=gen, judge=judge)
    events = parse_frames((await client.post("/agui/run", json=payload("a sign-up form"))).text)

    known = {s.id for s in LocalGuidelines().all()}
    assert len(calls) == 2 and all(ids and set(ids) <= known for ids in calls)
    assert "Checking the UI against the design guidelines…" in statuses(events)
    cited = LocalGuidelines().get(calls[0][0])
    assert f"Guideline {cited.cite()} (component submit): label isn't a verb Fix: say what happens" in prompts[1]
    judged = [c["result"]["summary"] for c in tool_calls(events) if c["name"] == "guidelines.judge"]
    assert judged == [f"1 issue(s): {cited.id}", "follows the guidelines"]


async def test_generate_with_data_grounds_the_generator_in_provider_data(client):
    gen, prompts = fake_generator(VALID_DOC)
    grounder = fake_grounder()
    use_graph(decide=decide_says("GENERATE", data=["plans.list", "no.such.provider"]), generate_ui=gen, grounder=grounder)
    events = parse_frames((await client.post("/agui/run", json=payload("I travel a lot, which plan fits?"))).text)

    assert "plans.list" in [c["name"] for c in tool_calls(events)]
    assert '"Unlimited Plus"' in prompts[0] and "Real data (the ONLY source" in prompts[0]
    assert set(grounder.seen[0]["dataFields"]) == {"summary", "plans"}
    meta = next(e for e in events if e["type"] == "CUSTOM" and e["name"] == "a2ui")["value"]["meta"]
    assert meta["decision"]["dataProviders"] == ["plans.list"]  # POLICY dropped the unknown provider
    assert meta["grounding"]["dataFields"] == ["plans", "summary"]


async def test_grounding_failure_still_builds_the_ui(client):
    async def broken_brief(system, inputs):
        raise RuntimeError("brief model down")

    gen, prompts = fake_generator(VALID_DOC)
    use_graph(decide=decide_says("GENERATE"), generate_ui=gen,
              grounder=Grounder(guidelines=Guidelines([LocalGuidelines()]), mcp=None, brief=broken_brief))
    events = parse_frames((await client.post("/agui/run", json=payload("a sign-up form"))).text)
    assert prompts[0] == "a sign-up form"  # no brief: the plain request
    assert any(e["type"] == "CUSTOM" and e["name"] == "a2ui" for e in events)
