"""REFINE: modify a surface that's on screen (P8).

The simple loop: take the surface as it is now, give its components and the
user's request to the model, and get back only what changes (update / add /
remove, plus "split" to give particular list items their own copies); code
applies that to the surface, then

  check    graph check -> schema gate -> hard-rule lints -> data contract (bind only
           to data the surface has) -> targeting (a change for particular list items
           mustn't restyle the one component every item is drawn from)
  repair   the errors and the rejected list go back to the model (A2UI_MAX_REPAIRS)
  diff     code computes what changed (JSON Patch over the component view), for the
           card, the lineage and the judge; the model doesn't have to describe it
  judge    soft rules, on the change only; findings the surface already had are dropped

The data model never passes through the model's reply: it's re-attached as it was,
so values can't drift. Works for any surface: a curated screen, a variant, or UI
the generator made.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Awaitable
from dataclasses import dataclass, field
from typing import Any

import jsonpatch

from ..config import settings
from ..data.providers import field_matches, pointer_patterns
from ..generation.gate import validate_a2ui_document
from ..generation.generate import collect_errors
from ..generation.graph_check import validate_and_repair_graph
from ..generation.llm import generate_a2ui
from ..generation.prompt import schema_json
from ..graph.trace import Tracer
from ..grounding.sources import Source
from ..templates.render import binding_paths, component_scopes
from ..verify.judge import JudgeFn
from ..verify.lints import lint_messages
from .patching import PatchError, _data_model, _pointer, describe_patch, is_list_template, item_labels, list_items, to_view, unroll
from .variants import COMMON_COMPONENTS, GenerateFn, schema_subset, targeting_errors

# The reply holds only what changes and code applies it: measured on tests/test_modify_eval.py it is as
# accurate as returning the whole list and 2-20x faster (a split of 5 rich tiles: ~4 s vs ~80 s), and
# nothing the model didn't mention can drift.
SYSTEM = """You modify an existing UI built with a design system (A2UI v0.9: a flat list of components, each
with a unique "id" and a "component" name; a parent lists child ids in "children"; bindings are {"path": ...}).

You get the screen's current components and the change the user wants. Reply with ONLY what changes; code applies it
to the screen and everything you don't mention stays exactly as it is:
- "update": [{"id": "<existing id>", ...only the props that change}]. Props are merged in: nested objects merge,
  lists (like "children") are replaced whole, and null removes a prop.
- "add": [<complete new component, with a new unique id>]. Also update its parent's "children" so it appears where
  it should.
- "remove": ["<id>", ...]. Code also drops removed ids from every "children" list.
- Change only what the request asks for. Don't restyle, reword or restructure anything else.
- Use only the components and props in the schemas below, with their exact shapes.
- The data model stays as it is; you can't change its values. Bind only to the listed data fields and never write
  data values (names, prices, dates, statuses…) as literal text. UI copy is different and fine as literal text:
  headings, labels, button text, helper lines, and any wording the user gives you ("add a line saying …"). A field
  means only what its name says. If the change needs content data that isn't there, don't invent it: list it in
  missingData ({"field", "why"}) and, if useful, show a neutral placeholder that states no value ("Details: data
  needed").
- New inputs (a field, checkbox, toggle…) need somewhere to keep their value: add it in "newState" as
  {"/json/pointer": initial value} at a path that doesn't exist yet, and bind the input to it. Initial values are
  UI state only: "", false, true, 0, null or []. Never content.
- Lists: a container with children {"path": "/items", "componentId": "item-card"} draws ONE component per item, so
  updating "item-card" changes EVERY item. To change only particular items (e.g. "the featured one", "the second
  row", "the delayed orders"), put the container's id in "split": code replaces the template with one copy of the
  item's components per item, named "<id>-<index>" ("item-card-2", and "item-body-2" for a component inside it),
  with their bindings made absolute. Then "update" only the copies of the items meant, with only the props that
  change. Never write the copies out yourself: "split" makes them. Find which items are meant (and their indexes)
  in data.lists; item values are there for choosing items only.
- Set "targets" from the REQUEST: "some" when it singles out particular list items, "all" when it's about every
  item alike, "screen" otherwise.
- Only if the change can't be made at all (it needs a prop the design system doesn't have), leave the changes empty
  and explain in "blocked" what would make it possible.

Respond with ONE JSON object:
{"summary": "<one sentence: what you changed>", "targets": "all|some|screen", "split": [], "update": [], "add": [],
 "remove": [], "newState": {}, "missingData": [], "blocked": ""}

Component schemas ($defs are shared types):
"""


@dataclass
class Modification:
    components: list[dict[str, Any]] | None  # set only if a model sends the whole list anyway (tolerated)
    summary: str = ""
    split: list[str] = field(default_factory=list)
    update: list[dict[str, Any]] = field(default_factory=list)
    add: list[dict[str, Any]] = field(default_factory=list)
    remove: list[str] = field(default_factory=list)
    targets: str = ""
    missing_data: list[dict[str, str]] = field(default_factory=list)
    blocked: str = ""
    new_state: dict[str, Any] = field(default_factory=dict)  # new UI-state paths for new inputs: pointer -> initial value


def _is_ui_state(value: Any) -> bool:
    """Initial values a new input may start with: never content (no text, no non-zero numbers)."""
    return value in ("", 0, None, []) or isinstance(value, bool)


def state_errors(doc: dict[str, Any], new_state: dict[str, Any]) -> list[str]:
    data = _data_model(doc)
    errors = []
    for path, value in new_state.items():
        if not isinstance(path, str) or not path.startswith("/") or path == "/":
            errors.append(f'newState key {path!r} must be a JSON pointer like "/form/darkMode".')
        elif _pointer(data, path) is not None:
            errors.append(f"newState {path} already exists in the data; bind to it instead of redefining it.")
        elif not _is_ui_state(value):
            errors.append(f'newState {path} = {value!r} is content, not UI state; start inputs at "", false, true, 0, null or [].')
    return errors


def with_state(doc: dict[str, Any], new_state: dict[str, Any]) -> dict[str, Any]:
    """`doc` plus one updateDataModel per new UI-state path (before the components that bind to it)."""
    if not new_state:
        return doc
    out = copy.deepcopy(doc)
    surface_id = next((m[k]["surfaceId"] for m in out["a2ui"] for k in m if k != "version"), "main")
    adds = [{"version": "v0.9", "updateDataModel": {"surfaceId": surface_id, "path": p, "value": v}} for p, v in new_state.items()]
    at = next((i for i, m in enumerate(out["a2ui"]) if "updateComponents" in m), len(out["a2ui"]))
    out["a2ui"][at:at] = adds
    return out


@dataclass
class ModifyResult:
    ok: bool
    mod: Modification | None = None
    doc: dict[str, Any] | None = None
    patch: list[dict[str, Any]] = field(default_factory=list)  # what changed, computed by code
    changes: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    flags: list[dict[str, Any]] = field(default_factory=list)
    attempts: int = 0
    schema: dict[str, Any] = field(default_factory=dict)
    model: str = ""

    @property
    def blocked(self) -> str:
        return self.mod.blocked if self.mod else ""


def _dicts(v: Any) -> list[dict[str, Any]]:
    return [x for x in v if isinstance(x, dict)] if isinstance(v, list) else []


def _strs(v: Any) -> list[str]:
    return [x for x in v if isinstance(x, str)] if isinstance(v, list) else []


def parse_modification(raw: Any) -> Modification:
    if not isinstance(raw, dict):
        raise ValueError("the reply is not a JSON object")
    full = isinstance(raw.get("components"), list)
    if not full and not any(k in raw for k in ("update", "add", "remove", "split", "blocked")):
        raise ValueError('the reply has neither changes ("update", "add", "remove", "split") nor "components"')
    missing = [
        {"field": str(m.get("field", "")), "why": str(m.get("why", ""))} if isinstance(m, dict) else {"field": str(m), "why": ""}
        for m in raw.get("missingData") or []
    ]
    return Modification(
        components=_dicts(raw["components"]) if full else None,
        summary=str(raw.get("summary") or ""),
        split=_strs(raw.get("split")),
        update=_dicts(raw.get("update")),
        add=_dicts(raw.get("add")),
        remove=_strs(raw.get("remove")),
        targets=str(raw.get("targets") or "").strip().lower(),
        missing_data=[m for m in missing if m["field"]],
        blocked=str(raw.get("blocked") or "").strip(),
        new_state=raw.get("newState") if isinstance(raw.get("newState"), dict) else {},
    )


def _merge(target: Any, patch: Any) -> Any:
    """JSON Merge Patch (RFC 7386): objects merge, anything else replaces, null deletes."""
    if not isinstance(patch, dict):
        return copy.deepcopy(patch)
    out = dict(target) if isinstance(target, dict) else {}
    for k, v in patch.items():
        if v is None:
            out.pop(k, None)
        else:
            out[k] = _merge(out.get(k), v)
    return out


def apply_changes(base: dict[str, Any], mod: Modification) -> tuple[list[dict[str, Any]], list[str]]:
    """The complete component list after a changes reply, plus errors for anything that can't apply."""
    view, errors = to_view(base), []
    before = set(view["components"])
    for container in mod.split:
        try:
            view = unroll(view, _data_model(base), container)
        except PatchError as err:
            errors.append(f"split: {err}")
    comps = view["components"]
    made_by_split = set(comps) - before
    for u in mod.update:
        cid = u.get("id")
        if cid not in comps:
            errors.append(f'update: there is no component "{cid}"' + (" (did you split its list first?)" if mod.split or "-" in str(cid) else ""))
            continue
        comps[cid] = _merge(comps[cid], {k: v for k, v in u.items() if k != "id"})
    for a in mod.add:
        cid = a.get("id")
        if cid in made_by_split:
            # The model wrote out a copy the split already made: take its version of that copy.
            comps[cid] = {k: v for k, v in a.items() if k != "id"}
            continue
        if not isinstance(cid, str) or cid in comps:
            errors.append(f"add: {cid!r} needs a new, unique id" if cid in comps else f"add: component without an id: {a}")
            continue
        comps[cid] = {k: v for k, v in a.items() if k != "id"}
    gone = set(mod.remove)
    for cid in gone:
        if comps.pop(cid, None) is None:
            errors.append(f'remove: there is no component "{cid}"')
    for body in comps.values():
        for key in ("children",):
            if isinstance(body.get(key), list):
                body[key] = [c for c in body[key] if c not in gone]
        if body.get("child") in gone:
            body.pop("child")
    return [{"id": cid, **body} for cid, body in comps.items()], errors


def with_components(doc: dict[str, Any], components: list[dict[str, Any]]) -> dict[str, Any]:
    """`doc` with its component list replaced; createSurface and the data model stay as they were."""
    out = copy.deepcopy(doc)
    msgs = [m for m in out["a2ui"] if "updateComponents" not in m]
    surface_id = next((m[k]["surfaceId"] for m in out["a2ui"] for k in m if k != "version"), "main")
    msgs.append({"version": "v0.9", "updateComponents": {"surfaceId": surface_id, "components": copy.deepcopy(components)}})
    out["a2ui"] = msgs
    return out


def prompts(doc: dict[str, Any], request: str, guidelines: list[Source], suggested: list[str]) -> tuple[str, str]:
    view = to_view(doc)["components"]
    names = [b.get("component") for b in view.values()] + list(suggested) + list(COMMON_COMPONENTS)
    system = SYSTEM + schema_json(schema_subset([n for n in names if isinstance(n, str)]))
    user = json.dumps({
        "change": request,
        "components": [{"id": cid, **body} for cid, body in view.items()],
        "data": {
            "fields": sorted(pointer_patterns(_data_model(doc))),
            # For finding "the featured item" and the like; never copy these values into text.
            "lists": list_items(doc),
        },
        "guidelines": [{"id": s.id, "title": s.title, "text": s.text} for s in guidelines],
        "componentsTheDesignSystemSuggests": suggested,
    }, ensure_ascii=False, indent=1)
    return system, user


def repair_prompt(user: str, mod: Modification, errors: list[str]) -> str:
    if mod.components is not None:
        rejected = f"Rejected components:\n{json.dumps(mod.components, ensure_ascii=False)}"
    else:
        rejected = "Rejected reply (it applies to the screen as given above, not to its own result):\n" + json.dumps(
            {"split": mod.split, "update": mod.update, "add": mod.add, "remove": mod.remove, "newState": mod.new_state},
            ensure_ascii=False)
    return (
        f"{user}\n\nYour modification was REJECTED by the design-system checks. Fix ONLY these errors and return "
        "the corrected, complete reply in the same JSON format:\n"
        + "\n".join(f"- {e}" for e in errors)
        + f"\n\n{rejected}"
    )


def diff(before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, Any]]:
    """What changed, as JSON Patch over the component view (order-insensitive: components are keyed by id).

    When the model split a list into one component per item (to change particular items), the split
    is replayed first with the deterministic `unroll`, so the diff shows one "split" line plus the real
    change instead of every copied component. The result stays replayable with apply_patch.
    """
    old, new = to_view(before), to_view(after)
    ops: list[dict[str, Any]] = []
    for cid, body in list(old["components"].items()):
        was_list = is_list_template(body.get("children"))
        now_static = isinstance(new["components"].get(cid, {}).get("children"), list)
        if was_list and now_static:
            try:
                old = unroll(old, _data_model(before), cid)
                ops.append({"op": "unroll", "path": f"/components/{cid}"})
            except PatchError:
                pass
    return ops + jsonpatch.make_patch(old, new).patch


def check(base: dict[str, Any], mod: Modification) -> tuple[dict[str, Any], list[dict[str, Any]], list[str], dict[str, Any]]:
    """(modified doc, patch, errors, schema validation). Deterministic checks only."""
    if mod.components is None:
        components, apply_errors = apply_changes(base, mod)
        if apply_errors:
            return base, [], apply_errors, {}
    else:
        components = mod.components
    ids = [c.get("id") for c in components]
    dupes = sorted({i for i in ids if isinstance(i, str) and ids.count(i) > 1})
    if dupes:
        return base, [], [f"Duplicate component ids: {', '.join(dupes)}. Every id must be unique."], {}
    bad_state = state_errors(base, mod.new_state)
    if bad_state:
        return base, [], bad_state, {}
    doc = with_state(with_components(base, components), mod.new_state)
    # A component nothing shows is a mistake here (a forgotten parent, a stale copy), not something to
    # hang off the root the way generation's graph repair would.
    shown = set(component_scopes(doc))
    stray = [c["id"] for c in components if isinstance(c.get("id"), str) and c["id"] not in shown]
    if stray and "root" in shown:
        return base, [], [f"Not placed on the screen: {', '.join(stray)}. Put each in a parent's children, or remove it."], {}
    graph = validate_and_repair_graph(doc)
    schema = validate_a2ui_document(doc)
    errors = collect_errors(graph, schema)
    if not errors:
        errors = lint_messages(doc)[0]
    fields = frozenset(pointer_patterns(_data_model(doc)))
    if not errors:
        errors = [
            f'Component "{cid}" binds to {p}, which isn\'t in the data. Bind only to the listed fields; if the change '
            "needs this data, remove the binding and list the field in missingData instead."
            for cid, p in binding_paths(doc) if not field_matches(fields, p)
        ]
    patch = diff(base, doc)
    if not errors:
        errors = targeting_errors(doc, patch, mod.targets) if patch else []
    return doc, patch, errors, schema


async def modify(
    base: dict[str, Any],
    request: str,
    *,
    guidelines: list[Source] | None = None,
    suggested: list[str] | None = None,
    generate: GenerateFn = generate_a2ui,
    judge: JudgeFn | None = None,
    soft_rules: list[Source] | None = None,
    base_issues: Awaitable[set[str]] | None = None,
    max_repairs: int | None = None,
    tracer: Tracer | None = None,
    label: str = "surface",
) -> ModifyResult:
    max_repairs = settings.max_repairs if max_repairs is None else max_repairs
    tracer = tracer or Tracer.off()
    soft_rules = soft_rules or []
    total = max_repairs + 1
    system, user = prompts(base, request, guidelines or [], suggested or [])
    prompt = user
    result = ModifyResult(ok=False)
    for attempt in range(total):
        result.attempts = attempt + 1
        async with tracer.tool("modify_surface", {"target": label, "attempt": attempt + 1, "of": total}) as call:
            try:
                res = await generate(system, prompt)
                mod = result.mod = parse_modification(res["json"])
                result.model = res.get("model", "")
            except ValueError as err:  # empty / truncated / not the expected shape: a failed attempt
                result.errors = [f"The previous reply was not usable: {err}"]
                call.set(f"no usable reply: {err}")
                continue
            if mod.blocked:
                call.set(f"not changed: {mod.blocked}")
                return result
            doc, patch, errors, schema = check(base, mod)
            result.doc, result.patch, result.schema, result.errors = doc, patch, schema, errors
            result.changes = describe_patch(patch, component_scopes(doc), item_labels(doc))
            call.set(f"{len(patch)} change(s), passes the checks" if not errors else f"rejected: {len(errors)} error(s)",
                     summary_of_change=mod.summary, changes=result.changes, errors=errors)
        if not errors:
            if not patch:
                result.ok = True
                return result
            if judge and soft_rules:
                async with tracer.tool("guidelines.judge", {"target": label, "rules": [r.id for r in soft_rules]}) as call:
                    found = await judge(doc, soft_rules, request, change="\n".join(f"- {c}" for c in result.changes))
                    known = await base_issues if base_issues is not None else set()
                    dropped = sorted({v.ruleId for v in found if v.ruleId in known})
                    found = [v for v in found if v.ruleId not in known]
                    note = f" ({', '.join(dropped)} already on the screen before, not flagged)" if dropped else ""
                    call.set((f"{len(found)} issue(s): {', '.join(v.ruleId for v in found)}" if found else "follows the guidelines") + note,
                             violations=[v.model_dump() for v in found])
                result.flags = [v.model_dump() for v in found]
            result.ok = True
            return result
        prompt = repair_prompt(user, mod, errors)
    return result
