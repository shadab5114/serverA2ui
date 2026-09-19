"""ADAPT / REFINE builder: patches against a curated screen, verified one by one (P8).

  propose    one JSON-mode call: N distinct variants of the screen, each a JSON
             Patch (see patching.py) with a title, a rationale, the guideline ids
             it relies on, and the data it would need but no provider has
  verify     per variant: patch applies -> graph check -> schema gate ->
             hard-rule lints -> data contract (bind only to provider fields);
             errors go back to the model for that variant alone (A2UI_MAX_REPAIRS)
  judge      soft rules, once the variant is valid. Per persona policy
             (onGuidelineConflict): "flag" ships the variant with the flags
             shown on its card, "repair" feeds them to the repair loop

The prompt carries only the schemas the screen uses plus a few common
components, not the whole catalog: a patch touches little, so it needs little.
"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from ..config import settings
from ..data.providers import Provider, field_matches
from ..generation.gate import validate_a2ui_document
from ..generation.graph_check import validate_and_repair_graph
from ..generation.llm import generate_a2ui
from ..generation.generate import collect_errors
from ..generation.prompt import schema_json
from ..graph.trace import Tracer
from ..grounding.catalog import generation_catalog
from ..grounding.sources import Source
from ..templates.render import binding_paths, component_scopes
from ..verify.judge import JudgeFn, violation_message
from ..verify.lints import lint_messages
from .patching import PatchError, apply_patch, check_ops, describe_patch, item_labels, list_items, to_view

GenerateFn = Callable[[str, str], Awaitable[dict[str, Any]]]  # (system, user) -> {json, provider, model}

# Offered on top of what the screen already uses: the usual building blocks of a change.
COMMON_COMPONENTS = ("Text", "Badge", "Notification", "Button", "Column", "Row", "Divider", "Accordion", "AccordionItem")


@dataclass
class Proposal:
    title: str
    rationale: str
    sources: list[str]
    missing_data: list[dict[str, str]]
    patch: list[dict[str, Any]]
    blocked: str = ""  # why the change can't be made as asked (e.g. it targets one list item)
    targets: str = ""  # which list items the request is about: "all", "some" or "screen" (checked)

    def as_json(self) -> dict[str, Any]:
        return {"targets": self.targets, "title": self.title, "rationale": self.rationale, "sources": self.sources,
                "missingData": self.missing_data, "blocked": self.blocked, "patch": self.patch}


@dataclass
class Screen:
    """What the variants patch: a rendered surface (template + data, maybe earlier patches)."""

    doc: dict[str, Any]
    provider: Provider
    ref: str  # e.g. "plan-tiles@1", or "var-2 rev 1 (plan-tiles@1)"


@dataclass
class VariantResult:
    proposal: Proposal
    ok: bool
    doc: dict[str, Any] | None = None
    errors: list[str] = field(default_factory=list)
    flags: list[dict[str, Any]] = field(default_factory=list)
    attempts: int = 1
    schema: dict[str, Any] = field(default_factory=dict)
    graph_repaired: bool = False
    model: str = ""
    blocked: str = ""
    dropped_flags: list[str] = field(default_factory=list)  # judge findings the base screen already has

    @property
    def changes(self) -> list[str]:
        if not self.doc:
            return describe_patch(self.proposal.patch)
        return describe_patch(self.proposal.patch, component_scopes(self.doc), item_labels(self.doc))


# --- prompt ---------------------------------------------------------------------

SYSTEM = """You are a product designer exploring changes to a PRODUCTION screen built with a design system
(A2UI v0.9: a flat list of components; a parent lists child ids in "children"; bindings are {"path": ...}).

You change the screen ONLY with JSON Patch (RFC 6902) operations against this view of it:
  {"components": {"<id>": {"component": "<Name>", ...props}}}
- A component's id is its key. Add a component with {"op":"add","path":"/components/<new-id>","value":{"component":"Text",...}}
  AND reference it from a parent, e.g. {"op":"add","path":"/components/<parent-id>/children/1","value":"<new-id>"}.
  Use "-" as the index to append to a children list. Give new components short, unique, descriptive ids.
- Every path starts with /components/. The data model comes from a data provider: never patch it.
- Change only what the variant needs; everything else must stay exactly as it is.
- Use only the components and props in the schemas below, with their exact shapes.
- Bind only to the data fields listed. Inside a component that renders once per list item, bind RELATIVE to
  the item (no leading slash, e.g. {"path": "name"}); elsewhere use absolute paths ("/summary").
- A component in a list-item scope (see data.listItemScopes) is ONE component drawn once per item: a static
  change to it changes EVERY item. A change can differ per item only through a prop whose schema accepts a
  binding ({"path": ...}), bound to a per-item field. Many props (e.g. enum colours) don't accept bindings.
- To change PARTICULAR items (e.g. "the featured one", "the third row"), first split the list with the
  extension op {"op": "unroll", "path": "/components/<list container>"} (containers are in data.lists). It
  replaces the list template with one copy of the item's components per item: the copy of "item-card" for item
  2 is "item-card-2", and every component inside it gets the same suffix ("item-body-2", "item-action-2").
  Nested lists inside an item stay templates. Then patch only the copies you mean, e.g.
  [{"op":"unroll","path":"/components/item-list"},
   {"op":"replace","path":"/components/item-card-2/<prop>","value":"<new value>"}].
  Find the right items in data.lists (their values are for choosing items only; never copy them into text).
  An unroll is fixed to the items shown now; say so in the rationale.
- Never change every item so that one of them stands out (restyling every card to "highlight" one): it
  highlights nothing. Only a request about all items may change all items.
- Set "targets" first, from the REQUEST: "some" when it singles out particular items (a named one, "the
  featured one", "option 3", "highlight one"), "all" when it's about every item alike, "screen" when it isn't
  about the list items. A "some" variant must not change list-item components statically (unroll first); it's checked.
- Only when a change truly can't be made (it needs data or a prop that doesn't exist), return the variant with an
  empty patch and "blocked": one or two sentences saying why and what would make it possible.
- Never write data values (names, prices, dates, statuses…) as literal text: they come from data. UI copy
  (headings, labels, button text, helper lines, wording the designer gives you) is fine as literal text.
- A field means only what its name says. Never repurpose one to stand in for other information (a field about
  one thing is not a stand-in for a related thing the data doesn't have).
- If the change needs data that no listed field has, do NOT bind to it and do NOT invent values: list it in
  missingData ({"field": "<proposed field name>", "why": "<what it would hold>"}). The variant may still show
  where it would go, with a neutral static placeholder that states no value (e.g. "Details: data needed").
- In sources, cite the ids of the given guidelines the variant relies on (only those ids).

Respond with ONE JSON object:
{"variants": [{"targets": "all|some|screen", "title": "<2-5 words>", "rationale": "<one sentence: what changes and why>",
  "sources": ["DS-203"], "missingData": [], "blocked": "", "patch": [<operations>]}]}

Component schemas ($defs are shared types):
"""


def _refs(value: Any, out: set[str]) -> None:
    if isinstance(value, dict):
        ref = value.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/$defs/"):
            out.add(ref.split("/")[-1])
        for v in value.values():
            _refs(v, out)
    elif isinstance(value, list):
        for v in value:
            _refs(v, out)


def schema_subset(names: list[str]) -> dict[str, Any]:
    """The named components' schemas plus every $def they reach, transitively."""
    catalog = generation_catalog()
    components = {n: catalog["components"][n] for n in dict.fromkeys(names) if n in catalog["components"]}
    wanted: set[str] = set()
    _refs(components, wanted)
    done: set[str] = set()
    while wanted - done:
        name = (wanted - done).pop()
        done.add(name)
        if name in catalog["defs"]:
            _refs(catalog["defs"][name], wanted)
    return {"components": components, "$defs": {k: catalog["defs"][k] for k in sorted(done) if k in catalog["defs"]}}


def system_prompt(screen: Screen, extra_components: list[str]) -> str:
    used = [c.get("component") for c in to_view(screen.doc)["components"].values()]
    names = [n for n in [*used, *extra_components, *COMMON_COMPONENTS] if isinstance(n, str)]
    return SYSTEM + schema_json(schema_subset(names))


def data_fields(screen: Screen) -> dict[str, Any]:
    """The provider's fields, and which components render inside which list item (their relative scope)."""
    scopes: dict[str, list[str]] = {}
    for cid, scope in component_scopes(screen.doc).items():
        if scope:
            scopes.setdefault(scope, []).append(cid)
    fields = sorted(screen.provider.fields)
    return {
        "provider": screen.provider.name,
        "fields": fields,
        "listItemScopes": [
            {"scope": s, "components": ids,
             "relativeFields": sorted(f[len(s) + 1:] for f in fields if f.startswith(s + "/") and f != s)}
            for s, ids in sorted(scopes.items())
        ],
        # For targeting particular items only (which index is "the featured one"); never copy these as text.
        "lists": list_items(screen.doc),
    }


def user_prompt(
    task: str,
    screen: Screen,
    guidelines: list[Source],
    count: int,
    gaps: list[str] | None = None,
    suggested: list[str] | None = None,
) -> str:
    inputs = {
        "task": task,
        "variantsWanted": count,
        "gapsInTheScreen": gaps or [],
        "screen": {"ref": screen.ref, **to_view(screen.doc)},
        "data": data_fields(screen),
        "guidelines": [{"id": s.id, "title": s.title, "text": s.text} for s in guidelines],
        "componentsTheDesignSystemSuggests": suggested or [],
    }
    return json.dumps(inputs, ensure_ascii=False, indent=1)


def adapt_task(request: str, count: int) -> str:
    return (
        f'The designer asks: "{request}". Propose {count} DISTINCT variants of the screen that answer it: '
        "different directions (placement, structure, emphasis), not the same idea tweaked. Each variant is its "
        "own patch against the screen as given."
    )


def refine_task(request: str) -> str:
    return (
        f'The designer asks: "{request}". Make exactly that change to the screen as given, nothing else. '
        "Return one variant."
    )


def repair_prompt(base_user: str, proposal: Proposal, errors: list[str]) -> str:
    return (
        f"{base_user}\n\nYour variant \"{proposal.title}\" was REJECTED by the design-system checks. Fix ONLY these "
        "errors and return it corrected, as a single-variant object in the same format "
        '({"variants": [ { title, rationale, sources, missingData, patch } ]}). The patch still applies to the '
        "screen as given above, not to your previous result.\n\nErrors:\n"
        + "\n".join(f"- {e}" for e in errors)
        + f"\n\nRejected variant:\n{json.dumps(proposal.as_json(), ensure_ascii=False)}"
    )


# --- parse --------------------------------------------------------------------------

def parse_proposals(raw: Any, known_sources: set[str]) -> list[Proposal]:
    """Tolerant: {"variants": [...]}, a bare list, or a single variant object. Bad entries are dropped."""
    items = raw.get("variants") if isinstance(raw, dict) and "variants" in raw else raw
    if isinstance(items, dict):
        items = [items]
    out = []
    for v in items if isinstance(items, list) else []:
        if not isinstance(v, dict):
            continue
        missing = [
            {"field": str(m.get("field", "")), "why": str(m.get("why", ""))} if isinstance(m, dict) else {"field": str(m), "why": ""}
            for m in v.get("missingData") or []
        ]
        out.append(Proposal(
            title=str(v.get("title") or "Untitled variant")[:60],
            rationale=str(v.get("rationale") or ""),
            sources=[s for s in (v.get("sources") or []) if isinstance(s, str) and s in known_sources],
            missing_data=[m for m in missing if m["field"]],
            patch=v.get("patch") if isinstance(v.get("patch"), list) else [],
            blocked=re.sub(r"^blocked\s*:\s*", "", str(v.get("blocked") or "").strip(), flags=re.IGNORECASE),
            targets=str(v.get("targets") or "").strip().lower(),
        ))
    return out


# --- verify -------------------------------------------------------------------------

def data_contract_errors(doc: dict[str, Any], provider: Provider) -> list[str]:
    """A variant may bind only to fields its provider declares (the P8 data contract)."""
    errors = []
    for cid, pointer in binding_paths(doc):
        if not field_matches(provider.fields, pointer):
            errors.append(
                f'Component "{cid}" binds to {pointer}, which {provider.name} doesn\'t provide. Bind only to the listed '
                "fields; if the variant needs this data, remove the binding and list the field in missingData instead."
            )
    return errors


def targeting_errors(doc: dict[str, Any], patch: list[dict[str, Any]], targets: str) -> list[str]:
    """A variant for SOME list items must not change the one component every item is drawn from."""
    if targets != "some":
        return []
    every = [c for c in describe_patch(patch, component_scopes(doc)) if "(applies to every item" in c]
    return [
        f"This variant is for particular items, but {c.split(' (applies')[0]} applies to every item alike, so it "
        "doesn't single anything out. Start the patch with {\"op\": \"unroll\", \"path\": \"/components/<list container>\"} "
        "and change only the copies for the items meant (e.g. item-card-2)."
        for c in every
    ]


def check(
    screen: Screen, patch: list[dict[str, Any]], targets: str = ""
) -> tuple[dict[str, Any] | None, list[str], dict[str, Any], bool]:
    """(patched doc, errors, schema validation, graph repaired). Deterministic checks only."""
    try:
        doc = apply_patch(screen.doc, check_ops(patch))
    except PatchError as err:
        return None, [f"Patch: {err}"], {}, False
    graph = validate_and_repair_graph(doc)
    schema = validate_a2ui_document(doc)
    errors = collect_errors(graph, schema)
    if not errors:
        errors = lint_messages(doc)[0]
    if not errors:
        errors = data_contract_errors(doc, screen.provider)
    if not errors:
        errors = targeting_errors(doc, patch, targets)
    return doc, errors, schema, graph["repaired"]


async def propose(generate: GenerateFn, system: str, user: str, known_sources: set[str]) -> tuple[list[Proposal], str]:
    res = await generate(system, user)
    return parse_proposals(res["json"], known_sources), res.get("model", "")


async def finalize(
    proposal: Proposal,
    screen: Screen,
    *,
    system: str,
    user: str,
    request: str,
    known_sources: set[str],
    generate: GenerateFn = generate_a2ui,
    judge: JudgeFn | None = None,
    soft_rules: list[Source] | None = None,
    repair_soft: bool = False,
    max_repairs: int | None = None,
    tracer: Tracer | None = None,
    label: str = "variant",
    base_issues: Awaitable[set[str]] | None = None,
) -> VariantResult:
    """Verify one proposal, repairing it alone until it passes or repairs run out.

    base_issues: rule ids the judge already finds on the base screen (see judge_base); the
    same findings on a variant describe production, not the change, so they aren't flagged.
    """
    max_repairs = settings.max_repairs if max_repairs is None else max_repairs
    tracer = tracer or Tracer.off()
    soft_rules = soft_rules or []
    total = max_repairs + 1
    result = VariantResult(proposal, ok=False)
    for attempt in range(total):
        result.attempts = attempt + 1
        if proposal.blocked:
            # The model says the change can't be made as asked: that's an answer, not an error to repair.
            result.blocked = proposal.blocked
            return result
        async with tracer.tool("variant.check", {"variant": label, "title": proposal.title, "attempt": attempt + 1, "of": total}) as call:
            doc, errors, schema, repaired = check(screen, proposal.patch, proposal.targets)
            call.set(f"{label} passes the gate, lints and data contract" if not errors
                     else f"{label} rejected: {len(errors)} error(s)", errors=errors, patch=proposal.patch)

        flags: list[dict[str, Any]] = []
        if not errors and judge and soft_rules:
            async with tracer.tool("guidelines.judge", {"variant": label, "rules": [r.id for r in soft_rules]}) as call:
                change = "\n".join(f"- {c}" for c in describe_patch(proposal.patch, component_scopes(doc), item_labels(doc)))
                found = await judge(doc, soft_rules, request, change=change)
                known = await base_issues if base_issues is not None else set()
                result.dropped_flags = sorted({v.ruleId for v in found if v.ruleId in known})
                found = [v for v in found if v.ruleId not in known]
                dropped = f" ({', '.join(result.dropped_flags)} already on the base screen, not flagged)" if result.dropped_flags else ""
                call.set((f"{len(found)} issue(s): {', '.join(v.ruleId for v in found)}" if found else "follows the guidelines") + dropped,
                         violations=[v.model_dump() for v in found])
            if found and repair_soft and attempt < max_repairs:
                errors = [violation_message(v, soft_rules) for v in found]
            else:
                flags = [v.model_dump() for v in found]

        if not errors:
            result.ok, result.doc, result.flags, result.errors = True, doc, flags, []
            result.schema, result.graph_repaired = schema, repaired
            return result

        result.errors = errors
        if attempt == max_repairs:
            break
        async with tracer.tool("variant.repair", {"variant": label, "errors": len(errors)}) as call:
            try:
                fixed, model = await propose(generate, system, repair_prompt(user, proposal, errors), known_sources)
            except ValueError as err:  # unusable reply: count it as a failed attempt
                call.set(f"no usable JSON: {err}")
                continue
            call.set(f"{len(fixed[0].patch)} operation(s)" if fixed else "no variant returned")
            result.model = model or result.model
        if fixed:
            # Keep the variant's identity; take the corrected patch (and any updated notes).
            proposal = result.proposal = Proposal(
                title=proposal.title,
                rationale=fixed[0].rationale or proposal.rationale,
                sources=fixed[0].sources or proposal.sources,
                missing_data=fixed[0].missing_data or proposal.missing_data,
                patch=fixed[0].patch,
                blocked=fixed[0].blocked,
                targets=fixed[0].targets or proposal.targets,
            )
    return result


async def judge_base(judge: JudgeFn, doc: dict[str, Any], rules: list[Source], request: str, tracer: Tracer) -> set[str]:
    """Rule ids the judge finds on the base screen itself. Runs while the variants are being
    proposed; a failure just means nothing is subtracted."""
    async with tracer.tool("guidelines.judge", {"variant": "base screen", "rules": [r.id for r in rules]}) as call:
        try:
            found = await judge(doc, rules, request)
        except Exception as err:  # noqa: BLE001 — a backstop, not a gate
            call.set(f"skipped: {err}")
            return set()
        ids = {v.ruleId for v in found}
        call.set(f"already on the base screen: {', '.join(sorted(ids))}" if ids else "base screen follows the guidelines",
                 violations=[v.model_dump() for v in found])
    return ids
