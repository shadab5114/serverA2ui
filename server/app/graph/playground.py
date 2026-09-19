"""The one graph: decide -> (responder | template_builder | ground -> ui_generator | adapt | refine).

  decide:           DECIDE (one structured-output call) + POLICY (plain code, per persona)
                    -> a Plan: TEXT, TEMPLATE <id> or GENERATE, with a reason.
  responder:        TEXT, streams a plain-text answer.
  template_builder: TEMPLATE, fills a curated template with provider data, gates it.
  ground:           GENERATE, part 1 (P7): guidelines (local markdown / RAG), the catalog
                    MCP server and real provider data -> a cited design brief.
  ui_generator:     GENERATE, part 2: builds from the brief; VERIFY = schema gate +
                    hard-rule lints + soft-rule judge, with the repair loop.
  adapt:            ADAPT (P8, explorer): baseline + N patch variants (see explore.py).
  refine:           REFINE (P8): modify a surface on screen, the latest by default: the whole
                    surface + the request go to the model, then gate, lints, judge (explore/modify.py).

UI builders report through custom events the AG-UI bridge puts on the wire:
  "status"         -> CUSTOM status (progress: stage + elapsed seconds, see progress.py)
  "a2ui"           -> CUSTOM a2ui (the surface; meta.source + meta.decision say how it was made)
  "assistant_text" -> TEXT_MESSAGE_* (caption, or the apology when nothing valid could be built)
  "trace_*"        -> STEP_* and TOOL_CALL_* for the client's trace panel (see trace.py)
Conversation memory comes from the checkpointer, keyed by thread_id. The persona
comes from RunAgentInput.state.persona (default "assistant"). A UI action
(forwardedProps.a2uiAction, P6) enters as a "[UI action] …" turn: its scalar
context is merged into `selections`, and DECIDE sees which screen it came from
plus that screen's suggestedNext as hints.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from langchain_core.callbacks import adispatch_custom_event
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from ..config import settings
from ..data.providers import REGISTRY, ProviderError
from ..decide.decide import DecideFn, make_decide, turn_context
from ..decide.policy import Plan, apply_policy, fill_params_from_selections, resolve_persona
from ..explore.lineage import baseline_record, generated_record, label as surface_label, next_id, screen_lines
from ..explore.variants import GenerateFn as ExploreGenerateFn
from ..generation.generate import STAGE_GENERATE, generate_validated_a2ui
from ..ground.ground import Grounder, Grounding
from ..grounding.sources import Source
from ..log import current_log
from ..generation.llm import generate_a2ui
from ..templates.store import FileTemplateStore, TemplateError, TemplateStore
from ..verify.judge import JudgeFn, make_judge
from .explore import TEMPLATE_APOLOGY, card, make_adapt_node, make_refine_node, render_screen
from .progress import StatusTicker, send_status
from .state import GraphState, last_user_text
from .trace import TRACE

SYSTEM_PROMPT = (
    "You are a concise, friendly assistant inside a generative-UI app. "
    "Answer in plain text. Keep replies short unless asked for detail."
)

UI_CAPTION = "Here's the UI you asked for."
UI_APOLOGY = (
    "I couldn't build a valid UI for that. Could you rephrase or simplify the "
    "request? (The generated layout didn't pass validation.)"
)
STAGE_GROUND = "Grounding the UI in the design guidelines…"

GenerateUi = Callable[..., Awaitable[dict[str, Any]]]


def make_model() -> BaseChatModel:
    """Streaming chat model for the responder (token deltas flow to the client).

    gpt-5 / o-series only accept the default temperature (1); older models are
    fine with 1 too, so it's set explicitly to keep one code path.
    """
    return ChatOpenAI(model=settings.openai_model, temperature=1, streaming=True)


def make_decide_node(decide: DecideFn, store: TemplateStore):
    async def decide_node(state: GraphState) -> dict:
        """DECIDE + POLICY. Any DECIDE failure falls back to TEXT so the turn never breaks."""
        log = current_log.get()
        await send_status("Reading your request…")
        persona = resolve_persona(state.get("persona"))
        every = store.manifests()
        manifests = [m for m in every if persona.name in m.personas]

        # A UI action (P6): remember what the user chose, and find the screen it came from.
        action = state.get("action")
        # What's on screen (P8), shown to personas that may REFINE it.
        surfaces = state.get("surfaces") or {}
        latest = state.get("last_surface")
        screen = screen_lines(surfaces, latest)[-12:] if "REFINE" in persona.strategies else None
        ctx, chosen = turn_context(action, state.get("selections"), every, manifests, screen)
        if action and log:
            where = f" from {ctx.source.ref}" if ctx.source else " (undeclared event)"
            log.step(f"action: {action['name']} {chosen}{where}")

        async with TRACE.step("decide"), TRACE.tool("decide", {
            "persona": persona.name,
            "templates": [m.ref for m in manifests],
            **({"action": action["name"]} if action else {}),
        }) as call:
            try:
                decision = await decide(state["messages"], persona, manifests, ctx)
            except Exception as err:  # noqa: BLE001 — deciding must never break the turn
                if log:
                    log.warn(f"decide failed, falling back to TEXT — {err}")
                plan = Plan("TEXT", None, {}, f"decide failed: {err}", "TEXT", "none", [], "", persona.name)
                call.set(f"TEXT (fallback: {err})", plan=plan.as_meta())
                return {"plan": plan.as_meta(), "selections": chosen, "grounding": None}

            plan = apply_policy(decision, persona, manifests, on_screen=surfaces.keys(), latest=latest)
            if plan.template_id:
                template = next(m for m in manifests if m.id == plan.template_id)
                provider = REGISTRY.get(template.provider)
                fill_params_from_selections(plan, [p.name for p in provider.params] if provider else [], ctx.selections)
            ref = next((m.ref for m in manifests if m.id == plan.template_id), plan.template_id)
            label = f"{plan.strategy} {ref or plan.target or ''}".strip()
            if plan.strategy == "ADAPT":
                label += f" ×{plan.variants}"
            call.set(f"{label}: {plan.reason}", plan=plan.as_meta())

        if log:
            params = f" {plan.params}" if plan.params else ""
            data = f" data={plan.data_providers}" if plan.data_providers else ""
            log.step(f"decision: {label}{params}{data} ({plan.reason}) [{persona.name}, coverage {plan.coverage}]")
            if plan.gaps:
                log.step(f"gaps: {'; '.join(plan.gaps)}")
            for note in plan.notes:
                log.warn(f"policy: {note}")
        return {"plan": plan.as_meta(), "selections": chosen, "grounding": None}

    return decide_node


def make_responder(model: BaseChatModel):
    async def responder(state: GraphState) -> dict:
        reply = await model.ainvoke([SystemMessage(SYSTEM_PROMPT), *state["messages"]])
        return {"messages": [reply]}

    return responder


def make_template_builder(store: TemplateStore):
    async def template_builder(state: GraphState) -> dict:
        log = current_log.get()
        plan = state["plan"]
        persona = resolve_persona(state.get("persona"))
        async with TRACE.step("build"):
            try:
                template = store.get(plan["templateId"])
                await send_status(f"Loading the {template.manifest.title.lower()} screen…")
                rendered = await render_screen(template, plan["params"])
            except (TemplateError, ProviderError) as err:
                if log:
                    log.fail(f"template {plan['templateId']} failed — {err}")
                await adispatch_custom_event("assistant_text", {"text": TEMPLATE_APOLOGY})
                return {"messages": [AIMessage(TEMPLATE_APOLOGY)]}

        m = template.manifest
        schema = rendered["schema_validation"]
        # Lineage (P8): every curated screen shown is a baseline the explorer can adapt or refine.
        base_id = next_id(state.get("surfaces") or {}, "baseline")
        record = baseline_record(m.id, m.version, plan["params"], m.title, rendered["a2ui"])
        meta = {
            "source": {"kind": "template", "id": m.id, "version": m.version},
            "decision": plan,
            "schemaChecked": schema["checked"],
            "unknownComponents": schema["unknownComponents"],
        }
        if persona.show_rationale:
            meta["card"] = card(base_id, record, title=m.title)
        if log:
            log.step(f"template {m.ref} filled from {m.provider} and passed the gate ({base_id})")
        await adispatch_custom_event("a2ui", {"a2ui": rendered["a2ui"]["a2ui"], "meta": meta})
        await adispatch_custom_event("assistant_text", {"text": m.caption})
        return {"messages": [AIMessage(m.caption)], "surfaces": {base_id: record}, "last_surface": base_id}

    return template_builder


def make_ground_node(grounder: Grounder):
    async def ground(state: GraphState) -> dict:
        """Cited design brief + real data for the generator. Failure degrades to ungrounded generation."""
        log = current_log.get()
        async with TRACE.step("ground"), StatusTicker(STAGE_GROUND):
            try:
                g = await grounder.ground(last_user_text(state), state["plan"], TRACE)
            except Exception as err:  # noqa: BLE001 — grounding helps; it must not block the UI
                if log:
                    log.warn(f"grounding failed, generating without a brief — {err}")
                return {"grounding": None}
        if log:
            ids = [s["id"] for s in g.sources]
            log.step(f"brief: {g.brief['pattern']} · rules {[r['id'] for r in g.brief['rules']]} · sources {ids}")
            for note in g.notes:
                log.step(f"grounding note: {note}")
        return {"grounding": g.__dict__}

    return ground


def make_ui_generator(generate_ui: GenerateUi, judge: JudgeFn | None):
    async def ui_generator(state: GraphState) -> dict:
        grounding = Grounding(**state["grounding"]) if state.get("grounding") else None
        soft_rules: list[Source] = grounding.soft_rules() if grounding else []
        persona = resolve_persona(state.get("persona"))
        # UI generation is one non-streamed call plus possible repairs: 20-30 s
        # with nothing else on the wire. Report each stage, with a ticking timer.
        async with TRACE.step("build"), StatusTicker(STAGE_GENERATE) as ticker:
            result = await generate_ui(
                last_user_text(state),
                log=current_log.get(),
                on_status=ticker.stage,
                guidance=grounding.guidance if grounding else "",
                soft_rules=soft_rules,
                judge=judge,
                tracer=TRACE,
                repair_soft=persona.on_guideline_conflict == "repair",
            )
        if result["ok"]:
            meta = {**result["meta"], "source": {"kind": "generated"}, "decision": state.get("plan")}
            if grounding:
                meta["grounding"] = {
                    "brief": grounding.brief,
                    "sources": [s["id"] for s in grounding.sources],
                    "dataFields": sorted(grounding.data),
                    "notes": grounding.notes,
                }
            # Lineage (P8): generated UI can be modified later like any surface on screen.
            sid = next_id(state.get("surfaces") or {}, "generated")
            record = generated_record(result["a2ui"], (state.get("plan") or {}).get("intent") or last_user_text(state)[:80])
            meta["source"] = {"kind": "generated", "id": sid, "rev": 1}
            if persona.show_rationale:
                by_id = {s["id"]: s for s in grounding.sources} if grounding else {}
                brief = grounding.brief if grounding else {}
                pattern = f" · {brief['pattern']}" if brief.get("pattern", "none") != "none" else ""
                meta["card"] = {
                    "id": sid,
                    "kind": "generated",
                    "label": surface_label(sid, record) + pattern,
                    "rationale": brief.get("layout", ""),
                    "sources": [{"id": r["id"], "title": by_id[r["id"]]["title"]} for r in brief.get("rules", []) if r["id"] in by_id],
                    "flags": result["meta"].get("guidelines", {}).get("flags", []),
                }
            await adispatch_custom_event("a2ui", {"a2ui": result["a2ui"]["a2ui"], "meta": meta})
            await adispatch_custom_event("assistant_text", {"text": UI_CAPTION})
            # Chat history gets a compact caption; the surface itself lives in `surfaces`.
            return {"messages": [AIMessage(UI_CAPTION)], "surfaces": {sid: record}, "last_surface": sid}

        # The gate never passed: degrade to text instead of emitting broken UI.
        await adispatch_custom_event("assistant_text", {"text": UI_APOLOGY})
        return {"messages": [AIMessage(UI_APOLOGY)]}

    return ui_generator


ROUTES = {"TEXT": "responder", "TEMPLATE": "template_builder", "GENERATE": "ground", "ADAPT": "adapt", "REFINE": "refine"}


def route_edge(state: GraphState) -> str:
    return ROUTES.get((state.get("plan") or {}).get("strategy"), "responder")


_DEFAULT = object()


def build_graph(
    checkpointer: BaseCheckpointSaver,
    *,
    model: BaseChatModel | None = None,
    decide: DecideFn | None = None,
    generate_ui: GenerateUi = generate_validated_a2ui,
    store: TemplateStore | None = None,
    grounder: Grounder | None = None,
    judge: JudgeFn | None | object = _DEFAULT,
    explore_generate: ExploreGenerateFn = generate_a2ui,
):
    """explore_generate: the JSON-mode call ADAPT/REFINE propose patches with (a fake in tests)."""
    store = store or FileTemplateStore(settings.templates_dir)
    grounder = grounder or Grounder()
    if judge is _DEFAULT:
        judge = make_judge() if settings.guideline_judge else None
    workflow = StateGraph(GraphState)
    workflow.add_node("decide", make_decide_node(decide or make_decide(), store))
    workflow.add_node("responder", make_responder(model or make_model()))
    workflow.add_node("template_builder", make_template_builder(store))
    workflow.add_node("ground", make_ground_node(grounder))
    workflow.add_node("ui_generator", make_ui_generator(generate_ui, judge))
    workflow.add_node("adapt", make_adapt_node(store, grounder, explore_generate, judge))
    workflow.add_node("refine", make_refine_node(store, grounder, explore_generate, judge))
    workflow.add_edge(START, "decide")
    workflow.add_conditional_edges("decide", route_edge, {n: n for n in ROUTES.values()})
    workflow.add_edge("ground", "ui_generator")
    for node in ("responder", "template_builder", "ui_generator", "adapt", "refine"):
        workflow.add_edge(node, END)
    return workflow.compile(checkpointer=checkpointer)
