"""Explorer nodes (P8): ADAPT (baseline + N variants) and REFINE (patch one surface on screen).

  adapt:   baseline   the curated template with provider data, emitted first
           ground     guidelines + MCP for the request and DECIDE's gaps (no separate brief:
                      each variant carries its own rationale and citations)
           variants   one call proposes N patches; each is verified and repaired alone,
                      and emitted as soon as it passes (as_completed), not after all N
  refine:  rebuild the target (template + data + its patch chain), ground, one patch,
           verify, append it to the target's chain; other surfaces are untouched.
           The result renders as a new card in this turn ("Variant 2 · rev 2").

Every surface is recorded in `surfaces` (see explore/lineage.py). Soft-rule
conflicts follow the persona's onGuidelineConflict: "flag" shows them on the
card, "repair" repairs them. Variants go on the wire as ordinary CUSTOM a2ui
events; meta.card carries the label, rationale, sources, changes and flags.
"""

from __future__ import annotations

import asyncio
from typing import Any

from langchain_core.callbacks import adispatch_custom_event
from langchain_core.messages import AIMessage

from ..data.providers import ProviderError, get_provider
from ..decide.policy import Persona, resolve_persona
from ..explore.lineage import baseline_record, current_doc, label, next_id, ref, rev
from ..explore.modify import modify
from ..explore.patching import PatchError
from ..explore.variants import (
    GenerateFn,
    Screen,
    VariantResult,
    adapt_task,
    finalize,
    judge_base,
    propose,
    system_prompt,
    user_prompt,
)
from ..ground.ground import Grounder
from ..grounding.sources import GroundingResult, Source
from ..log import current_log
from ..templates.render import render_template
from ..templates.store import Template, TemplateError, TemplateStore
from ..verify.judge import JudgeFn
from .progress import StatusTicker, send_status
from .state import GraphState, last_user_text
from .trace import TRACE

TEMPLATE_APOLOGY = "I couldn't load that screen right now. Please try again in a moment."
STAGE_GROUND = "Grounding the change in the design guidelines…"
STAGE_CHECK = "Checking the variants against the design system…"


# --- shared -----------------------------------------------------------------------

async def render_screen(template: Template, params: dict[str, Any]) -> dict[str, Any]:
    """Traced template render. A bad param (e.g. an unknown plan id) shouldn't cost the user the screen."""
    log = current_log.get()
    async with TRACE.tool(template.manifest.provider, params) as call:
        try:
            rendered = render_template(template, params)
        except ProviderError as err:
            if log:
                log.warn(f"provider rejected params {params} — {err}; rendering without them")
            rendered = render_template(template, {})
        counts = ", ".join(f"{len(v)} {k}" for k, v in rendered["data"].items() if isinstance(v, list))
        call.set(f"{counts} → {template.manifest.ref}", data=rendered["data"])
    return rendered


def card(surface_id: str, record: dict[str, Any], **extra: Any) -> dict[str, Any]:
    """meta.card: what the client's variant card shows next to the surface."""
    return {"id": surface_id, "kind": record["kind"], "label": label(surface_id, record), "base": ref(record),
            "rev": rev(record), **{k: v for k, v in extra.items() if v not in (None, [], "")}}


def cite(ids: list[str], sources: dict[str, Source]) -> list[dict[str, str]]:
    return [{"id": i, "title": sources[i].title} for i in ids if i in sources]


async def emit(doc: dict[str, Any], meta: dict[str, Any]) -> None:
    await adispatch_custom_event("a2ui", {"a2ui": doc["a2ui"], "meta": meta})


async def say(text: str) -> dict[str, Any]:
    await adispatch_custom_event("assistant_text", {"text": text})
    return {"messages": [AIMessage(text)]}


def variant_meta(
    surface_id: str, record: dict[str, Any], result: VariantResult, plan: dict[str, Any], sources: dict[str, Source]
) -> dict[str, Any]:
    p = result.proposal
    return {
        "source": {"kind": record["kind"], "id": surface_id, "base": ref(record), "rev": rev(record)},
        "decision": plan,
        "model": result.model,
        "attempts": result.attempts,
        "graphRepaired": result.graph_repaired,
        "schemaChecked": result.schema.get("checked", []),
        "unknownComponents": result.schema.get("unknownComponents", []),
        "card": card(
            surface_id, record,
            title=record.get("title"), rationale=p.rationale, sources=cite(p.sources, sources),
            changes=result.changes, flags=result.flags, missingData=p.missing_data, patch=p.patch,
        ),
    }


async def _safe(task) -> VariantResult | Exception:
    try:
        return await task
    except Exception as err:  # noqa: BLE001 — one variant failing mustn't sink the others
        return err


async def _ground(grounder: Grounder, query: str, mcp_intent: str) -> tuple[list[Source], list[str], list[str]]:
    """(guideline sources, suggested component names, notes). Failure degrades to no grounding."""
    log = current_log.get()
    async with TRACE.step("ground"), StatusTicker(STAGE_GROUND):
        try:
            found, components, notes = await grounder.retrieve(query, TRACE, mcp_intent=mcp_intent)
        except Exception as err:  # noqa: BLE001 — grounding helps; it must not block the variants
            if log:
                log.warn(f"grounding failed, exploring without guidelines — {err}")
            found, components, notes = GroundingResult("", []), GroundingResult("", []), [str(err)]
    return found.sources, [s.title for s in components.sources], notes


def _soft(sources: list[Source]) -> list[Source]:
    return [s for s in sources if s.kind in ("soft", "pattern")]


def _judge_base(judge: JudgeFn | None, screen: Screen, found: list[Source], request: str) -> asyncio.Task | None:
    """Judge the base screen in the background: what it already breaks isn't a variant's doing."""
    soft = _soft(found)
    if not (judge and soft):
        return None
    return asyncio.create_task(judge_base(judge, screen.doc, soft, request, TRACE))


async def _settle(task: asyncio.Task | None) -> None:
    """Let the background base-screen judge finish (it's usually done) so no task outlives the node."""
    if task is not None:
        await task


def _missing_line(sid: str, record: dict[str, Any], missing: list[dict[str, str]]) -> str:
    fields = ", ".join(f"`{m['field']}`" + (f" ({m['why']})" if m.get("why") else "") for m in missing)
    return f"{label(sid, record)} needs data no provider has yet: {fields}."


# --- ADAPT ------------------------------------------------------------------------

def make_adapt_node(store: TemplateStore, grounder: Grounder, generate: GenerateFn, judge: JudgeFn | None):
    async def adapt(state: GraphState) -> dict:
        log = current_log.get()
        plan = state["plan"]
        persona = resolve_persona(state.get("persona"))
        request = last_user_text(state)
        surfaces = dict(state.get("surfaces") or {})
        recorded: dict[str, Any] = {}
        count = max(1, int(plan.get("variants") or persona.variants))

        # 1. Baseline: production as it is, shown first so there's something to look at right away.
        async with TRACE.step("baseline"):
            try:
                template = store.get(plan["templateId"])
                await send_status(f"Loading the {template.manifest.title.lower()} screen…")
                rendered = await render_screen(template, plan["params"])
            except (TemplateError, ProviderError) as err:
                if log:
                    log.fail(f"template {plan['templateId']} failed — {err}")
                return await say(TEMPLATE_APOLOGY)
            m = template.manifest
            base_id = next_id(surfaces, "baseline")
            base = baseline_record(m.id, m.version, plan["params"], m.title, rendered["a2ui"])
            surfaces[base_id] = recorded[base_id] = base
            await emit(rendered["a2ui"], {
                "source": {"kind": "template", "id": m.id, "version": m.version},
                "decision": plan,
                "schemaChecked": rendered["schema_validation"]["checked"],
                "unknownComponents": rendered["schema_validation"]["unknownComponents"],
                "card": card(base_id, base, title=m.title),
            })
        screen = Screen(rendered["a2ui"], get_provider(m.provider), m.ref)

        # 2. Ground the change.
        gaps = plan.get("gaps") or []
        found, suggested, notes = await _ground(
            grounder, f"{plan.get('intent') or ''}. {request}. {' '.join(gaps)}".strip(". "), "; ".join(gaps) or request
        )
        by_id = {s.id: s for s in found}

        # 3. Variants: propose N patches, verify each alone, emit each as it passes.
        async with TRACE.step("variants"), StatusTicker(f"Designing {count} variants of {m.title.lower()}…") as ticker:
            system = system_prompt(screen, suggested)
            user = user_prompt(adapt_task(request, count), screen, found, count, gaps, suggested)
            base_issues = _judge_base(judge, screen, found, request)  # runs while the variants are proposed
            async with TRACE.tool("propose_variants", {"base": m.ref, "variants": count}) as call:
                try:
                    proposals, model = await propose(generate, system, user, set(by_id))
                except ValueError as err:
                    proposals, model = [], ""
                    notes.append(f"no usable variants: {err}")
                proposals = proposals[:count]
                call.set(f"{len(proposals)} variant(s): " + "; ".join(p.title for p in proposals),
                         variants=[p.as_json() for p in proposals])

            await ticker.stage(STAGE_CHECK)
            tasks = [
                asyncio.create_task(_safe(finalize(
                    p, screen, system=system, user=user, request=request, known_sources=set(by_id),
                    generate=generate, judge=judge, soft_rules=_soft(found),
                    repair_soft=persona.on_guideline_conflict == "repair", tracer=TRACE, label=f"proposal {i + 1}",
                    base_issues=base_issues,
                )))
                for i, p in enumerate(proposals)
            ]
            shown: list[tuple[str, dict[str, Any], VariantResult]] = []
            failed: list[str] = []
            blocked: list[tuple[str, str]] = []  # (title, why it can't be done as asked)
            for next_done in asyncio.as_completed(tasks):
                result = await next_done
                if isinstance(result, Exception):
                    failed.append(str(result))
                    continue
                if result.blocked:
                    blocked.append((result.proposal.title, result.blocked))
                    continue
                if not result.ok:
                    failed.append(f'"{result.proposal.title}": {result.errors[0] if result.errors else "invalid"}')
                    continue
                result.model = result.model or model
                vid = next_id(surfaces, "variant")
                p = result.proposal
                record = {
                    "kind": "variant", "templateId": m.id, "version": m.version, "params": dict(plan["params"]),
                    "patches": [p.patch], "from": base_id, "title": p.title, "rationale": p.rationale,
                    "sources": p.sources, "missingData": p.missing_data, "doc": result.doc,
                }
                surfaces[vid] = recorded[vid] = record
                await emit(result.doc, variant_meta(vid, record, result, plan, by_id))
                shown.append((vid, record, result))
                if log:
                    flags = f", {len(result.flags)} flag(s)" if result.flags else ""
                    log.step(f"{vid} \"{p.title}\" valid on attempt {result.attempts}{flags}: {'; '.join(result.changes)}")
            await _settle(base_issues)

        if log:
            for note in notes:
                log.step(f"grounding note: {note}")
            for f in failed:
                log.warn(f"variant dropped — {f}")
            for title, why in blocked:
                log.step(f"variant \"{title}\" not built as asked — {why}")
        latest = shown[-1][0] if shown else base_id
        return {**await say(adapt_caption(m.title, count, shown, failed, blocked)), "surfaces": recorded, "last_surface": latest}

    return adapt


def adapt_caption(title: str, wanted: int, shown: list, failed: list[str], blocked: list[tuple[str, str]] = ()) -> str:
    cant = [f'"{t}" can\'t be done as asked: {why}' for t, why in blocked]
    if not shown:
        if cant:
            return "\n".join([f"Here's the current {title.lower()} screen. I didn't build a variant:", *cant])
        why = f" ({failed[0]})" if failed else ""
        return (f"Here's the current {title.lower()} screen. I couldn't make any variant pass the design-system "
                f"checks{why}. Try describing the change differently.")
    lines = [f"Here's the current {title.lower()} screen and {len(shown)} variant{'s' if len(shown) != 1 else ''}."]
    if failed:
        lines[0] += f" ({len(failed)} more didn't pass the design-system checks.)"
    lines += cant
    for vid, record, result in shown:
        if result.proposal.missing_data:
            lines.append(_missing_line(vid, record, result.proposal.missing_data))
        if result.flags:
            ids = ", ".join(sorted({f["ruleId"] for f in result.flags}))
            lines.append(f"{label(vid, record)} conflicts with {ids}: see its card.")
    lines.append('Refine one by name, e.g. "on variant 2, make the badge say Recommended".')
    return "\n".join(lines)


# --- REFINE -----------------------------------------------------------------------

def _clip(lines: list[str], most: int = 8) -> list[str]:
    return lines if len(lines) <= most else [*lines[:most], f"…and {len(lines) - most} more"]


def make_refine_node(store: TemplateStore, grounder: Grounder, generate: GenerateFn, judge: JudgeFn | None):
    async def refine(state: GraphState) -> dict:
        """Modify a surface on screen: the whole surface + the request go to the model (see explore/modify.py)."""
        log = current_log.get()
        plan = state["plan"]
        persona: Persona = resolve_persona(state.get("persona"))
        request = last_user_text(state)
        surfaces = dict(state.get("surfaces") or {})
        target = plan["target"]
        record = surfaces[target]
        name = label(target, record)

        await send_status(f"Opening {name}…")
        try:
            doc, notes = current_doc(record, store)
        except (TemplateError, ProviderError, PatchError) as err:
            if log:
                log.fail(f"can't reopen {target} — {err}")
            return await say(f"I couldn't reopen {name} to change it ({err}).")

        found, suggested, gnotes = await _ground(grounder, request, request)
        soft = _soft(found)
        by_id = {s.id: s for s in found}

        async with TRACE.step("modify"), StatusTicker(f"Changing {name}…"):
            base_issues = asyncio.create_task(judge_base(judge, doc, soft, request, TRACE)) if judge and soft else None
            result = await modify(
                doc, request, guidelines=found, suggested=suggested, generate=generate,
                judge=judge, soft_rules=soft, base_issues=base_issues, tracer=TRACE, label=target,
            )
            await _settle(base_issues)

        if result.blocked:
            if log:
                log.step(f"{target} not changed — {result.blocked}")
            return await say(f"I didn't change {name}: {result.blocked}")
        if not result.ok:
            why = result.errors[0] if result.errors else "no usable change came back"
            if log:
                log.warn(f"modify {target} failed — {why}")
            return await say(f"I couldn't apply that to {name} without breaking the design-system checks: {why}")
        if not result.patch:
            return await say(f"Nothing changed on {name}: that already matches what you asked for.")

        mod = result.mod
        if record["kind"] == "baseline":  # production is never edited: the change starts a new variant
            sid = next_id(surfaces, "variant")
            new = {"kind": "variant", "templateId": record["templateId"], "version": record["version"],
                   "params": dict(record.get("params") or {}), "patches": [result.patch], "from": target,
                   "title": mod.summary[:60] or "Modified", "rationale": mod.summary, "sources": [],
                   "missingData": mod.missing_data, "doc": result.doc}
        else:
            sid = target
            new = {**record, "patches": [*record["patches"], result.patch], "doc": result.doc,
                   "missingData": [*record.get("missingData", []), *mod.missing_data]}

        meta = {
            "source": {"kind": new["kind"], "id": sid, "base": ref(new), "rev": rev(new)},
            "decision": plan,
            "model": result.model,
            "attempts": result.attempts,
            "schemaChecked": result.schema.get("checked", 0),
            "unknownComponents": result.schema.get("unknownComponents", []),
        }
        if persona.show_rationale:
            meta["card"] = card(sid, new, title=new.get("title"), rationale=mod.summary, changes=_clip(result.changes),
                                flags=result.flags, missingData=mod.missing_data, patch=result.patch)
        await emit(result.doc, meta)
        if log:
            log.step(f"{sid} rev {rev(new)} valid on attempt {result.attempts}: {'; '.join(_clip(result.changes, 4))}")
            for note in [*notes, *gnotes]:
                log.step(f"note: {note}")

        lines = [f"{label(sid, new)}" + (f" (from {name})" if record["kind"] == "baseline" else "")
                 + f": {mod.summary or '; '.join(_clip(result.changes, 3))}"]
        if mod.missing_data:
            lines.append(_missing_line(sid, new, mod.missing_data))
        if result.flags:
            lines.append(f"It conflicts with {', '.join(sorted({f['ruleId'] for f in result.flags}))}"
                         + (": see its card." if persona.show_rationale else "."))
        others = [label(s, r) for s, r in surfaces.items() if s != sid]
        if others and persona.show_rationale:
            lines.append(f"Unchanged: {', '.join(others)}.")
        return {**await say("\n".join(lines)), "surfaces": {sid: new}, "last_surface": sid}

    return refine
