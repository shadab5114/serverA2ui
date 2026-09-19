"""JSON Patch (RFC 6902) over a surface's components, keyed by component id (P8).

Variants are patches against a baseline, never whole new surfaces, so unchanged
parts stay byte-identical to production and every variant reads as a diff.
Patches don't address the A2UI message list (index paths are fragile for a model
to write); they address a VIEW of it:

    {"components": {"root": {"component": "Column", "children": [...]}, "plan-tile": {...}}}

so an op reads `/components/plan-tile/cap`. A component's id is its key. Only
`/components/...` may change: the data model comes from the provider, never
from a patch.
"""

from __future__ import annotations

import copy
import re
from typing import Any

import jsonpatch

OPS = {"add", "remove", "replace", "move", "copy", "test"}


class PatchError(ValueError):
    pass


def _components_message(doc: dict[str, Any]) -> dict[str, Any]:
    for m in doc.get("a2ui", []):
        if "updateComponents" in m:
            return m["updateComponents"]
    raise PatchError("the surface has no updateComponents message")


def to_view(doc: dict[str, Any]) -> dict[str, Any]:
    comps = _components_message(doc)["components"]
    return {"components": {c["id"]: {k: v for k, v in c.items() if k != "id"} for c in comps}}


def from_view(doc: dict[str, Any], view: dict[str, Any]) -> dict[str, Any]:
    """A copy of `doc` whose components are the view's (in view order: the baseline's, then new ones)."""
    out = copy.deepcopy(doc)
    msg = _components_message(out)
    msg["components"] = [{"id": cid, **body} for cid, body in view["components"].items()]
    return out


def check_ops(patch: Any) -> list[dict[str, Any]]:
    if not isinstance(patch, list) or not patch:
        raise PatchError("the patch must be a non-empty list of JSON Patch operations")
    for i, op in enumerate(patch):
        if not isinstance(op, dict) or op.get("op") not in OPS | {UNROLL} or not isinstance(op.get("path"), str):
            raise PatchError(f"operation {i + 1} is not a JSON Patch operation ({{op, path, value?}}): {op!r}")
        for key in ("path", "from"):
            if key in op and not str(op[key]).startswith("/components/"):
                raise PatchError(f"operation {i + 1}: {key} {op[key]!r} is outside /components/ (data can't be patched)")
        if op["op"] in ("add", "replace", "test") and "value" not in op:
            raise PatchError(f"operation {i + 1} ({op['op']} {op['path']}) has no value")
        if op["op"] == UNROLL and op["path"].count("/") != 2:
            raise PatchError(f"operation {i + 1}: unroll takes a component, e.g. /components/plan-row")
    return patch


# --- unroll: one copy per list item, so particular items can differ ------------------
#
# A list template ({"path": "/plans", "componentId": "plan-tile"}) draws ONE component
# per item, so a static change to it changes every item. The extension op
#   {"op": "unroll", "path": "/components/plan-row"}
# replaces the template with one copy of the item's components per item in the data
# ("plan-tile-2" is item 2), their relative bindings made absolute ("/plans/2/name").
# Later ops can then change one copy. The unrolled list is fixed to the items the data
# has now. Nested lists inside the item (a tile's feature list) stay templates.

UNROLL = "unroll"
_SUFFIX = "-"  # "plan-tile-2": the naming the modify prompt suggests, so a model-made split diffs cleanly


def _data_model(doc: dict[str, Any]) -> Any:
    """The surface's data: every updateDataModel merged in order (generated UIs may seed several paths)."""
    root: Any = None
    for m in doc.get("a2ui", []):
        upd = m.get("updateDataModel")
        if not upd:
            continue
        path, value = upd.get("path", "/") or "/", copy.deepcopy(upd.get("value"))
        if path == "/":
            root = value
            continue
        root = root if isinstance(root, dict) else {}
        node, parts = root, [p for p in path.strip("/").split("/") if p]
        for part in parts[:-1]:
            node = node.setdefault(part, {}) if isinstance(node, dict) else {}
        if isinstance(node, dict) and parts:
            node[parts[-1]] = value
    return root


def _pointer(data: Any, path: str) -> Any:
    for part in [p.replace("~1", "/").replace("~0", "~") for p in path.strip("/").split("/") if p]:
        if isinstance(data, list) and part.isdigit() and int(part) < len(data):
            data = data[int(part)]
        elif isinstance(data, dict) and part in data:
            data = data[part]
        else:
            return None
    return data


def is_list_template(value: Any) -> bool:
    return isinstance(value, dict) and isinstance(value.get("path"), str) and isinstance(value.get("componentId"), str)


def _is_binding(value: Any) -> bool:
    return isinstance(value, dict) and set(value) == {"path"} and isinstance(value["path"], str)


def _item_scope(comps: dict[str, Any], root: str) -> list[str]:
    """The item component and everything drawn in the same data scope (not nested list items)."""
    out, todo = [], [root]
    while todo:
        cid = todo.pop(0)
        if cid in out or cid not in comps:
            continue
        out.append(cid)
        body = comps[cid]
        if isinstance(body.get("child"), str):
            todo.append(body["child"])
        ch = body.get("children")
        if isinstance(ch, list):
            todo += [c for c in ch if isinstance(c, str)]
        elif isinstance(ch, str):
            todo.append(ch)
    return out


def _absolute(value: Any, base: str) -> Any:
    """Relative bindings under `value` made absolute under `base`."""
    if _is_binding(value):
        return value if value["path"].startswith("/") else {"path": f"{base}/{value['path']}"}
    if isinstance(value, dict):
        return {k: _absolute(v, base) for k, v in value.items()}
    if isinstance(value, list):
        return [_absolute(v, base) for v in value]
    return value


def _copy_item(body: dict[str, Any], base: str, scope: set[str], n: int) -> dict[str, Any]:
    out = {}
    for key, value in body.items():
        if key == "child" and isinstance(value, str):
            out[key] = f"{value}{_SUFFIX}{n}" if value in scope else value
        elif key == "children" and is_list_template(value):  # a nested list: its items keep relative bindings
            path = value["path"] if value["path"].startswith("/") else f"{base}/{value['path']}"
            out[key] = {**value, "path": path}
        elif key == "children" and isinstance(value, list):
            out[key] = [f"{v}{_SUFFIX}{n}" if isinstance(v, str) and v in scope else v for v in value]
        elif key == "children" and isinstance(value, str) and value in scope:
            out[key] = f"{value}{_SUFFIX}{n}"
        else:
            out[key] = _absolute(copy.deepcopy(value), base)
    return out


def unroll(view: dict[str, Any], data: Any, container: str) -> dict[str, Any]:
    comps = view["components"]
    body = comps.get(container)
    if body is None:
        raise PatchError(f'unroll: there is no component "{container}"')
    template = body.get("children")
    if not is_list_template(template):
        raise PatchError(f'unroll: "{container}" isn\'t a list (its children aren\'t a {{path, componentId}} template)')
    if not template["path"].startswith("/"):
        raise PatchError(f'unroll: "{container}" is a list inside another list item; unroll the outer list first')
    items = _pointer(data, template["path"])
    if not isinstance(items, list):
        raise PatchError(f"unroll: the data has no list at {template['path']}")
    scope = _item_scope(comps, template["componentId"])
    copies = {
        f"{cid}{_SUFFIX}{n}": _copy_item(comps[cid], f"{template['path']}/{n}", set(scope), n)
        for n in range(len(items))
        for cid in scope
    }
    out = {cid: b for cid, b in comps.items() if cid not in scope}
    out[container] = {**body, "children": [f"{template['componentId']}{_SUFFIX}{n}" for n in range(len(items))]}
    out.update(copies)
    return {**view, "components": out}


def _identity(item: Any, fields: int) -> dict[str, str]:
    """The first few short string fields of a list item (id, name, badge…), enough to tell items apart."""
    if not isinstance(item, dict):
        return {"value": str(item)[:40]}
    short = [(k, v) for k, v in item.items() if isinstance(v, str) and len(v) <= 40]
    return dict(short[:fields])


def list_items(doc: dict[str, Any], fields: int = 4) -> list[dict[str, Any]]:
    """Top-level lists that could be unrolled, with a few identifying values per item (for targeting only)."""
    comps = to_view(doc)["components"]
    data = _data_model(doc)
    out = []
    for cid, body in comps.items():
        template = body.get("children")
        if is_list_template(template) and template["path"].startswith("/"):
            items = _pointer(data, template["path"])
            if isinstance(items, list):
                out.append({
                    "container": cid, "list": template["path"], "itemComponent": template["componentId"],
                    "items": [{"index": n, **_identity(it, fields)} for n, it in enumerate(items)],
                })
    return out


def item_labels(doc: dict[str, Any]) -> dict[str, str]:
    """Components bound to ONE list item ("plan-tile-2", bound to /plans/2/...) -> that item's name ("Unlimited Go")."""
    data = _data_model(doc)
    out: dict[str, str] = {}

    def paths(v: Any):
        if _is_binding(v):
            yield v["path"]
        elif isinstance(v, dict):
            for x in v.values():
                yield from paths(x)
        elif isinstance(v, list):
            for x in v:
                yield from paths(x)

    for cid, body in to_view(doc)["components"].items():
        for p in paths(body):
            hit = re.match(r"^(/.*?/\d+)(?:/|$)", p)
            item = _pointer(data, hit.group(1)) if hit else None
            if isinstance(item, dict):
                name = next((item[k] for k in ("name", "title", "label", "id") if isinstance(item.get(k), str)), None)
                if name:
                    out[cid] = name
                    break
    return out


def apply_patch(doc: dict[str, Any], patch: Any) -> dict[str, Any]:
    """A new surface: `doc` with `patch` applied to its components. `doc` is left untouched."""
    ops = check_ops(patch)
    view = to_view(doc)
    batch: list[dict[str, Any]] = []

    def flush(view: dict[str, Any]) -> dict[str, Any]:
        if not batch:
            return view
        try:
            return jsonpatch.apply_patch(view, batch, in_place=False)
        except (jsonpatch.JsonPatchException, jsonpatch.JsonPointerException) as err:
            raise PatchError(f"the patch doesn't apply to the current screen: {err}") from err
        finally:
            batch.clear()

    for op in ops:
        if op["op"] == UNROLL:
            view = unroll(flush(view), _data_model(doc), op["path"].split("/")[2])
        else:
            batch.append(op)
    view = flush(view)
    if not isinstance(view.get("components"), dict):
        raise PatchError("the patch replaced /components itself")
    for cid, body in view["components"].items():
        if not isinstance(body, dict) or not isinstance(body.get("component"), str):
            raise PatchError(f'component "{cid}" needs a "component" name')
        if "id" in body and body["id"] != cid:
            raise PatchError(f'component "{cid}" has a conflicting "id" {body["id"]!r}; its key is its id')
    for body in view["components"].values():
        body.pop("id", None)
    return from_view(doc, view)


def apply_chain(doc: dict[str, Any], patches: list[Any]) -> dict[str, Any]:
    for p in patches:
        doc = apply_patch(doc, p)
    return doc


def describe_patch(
    patch: list[dict[str, Any]], scopes: dict[str, str] | None = None, labels: dict[str, str] | None = None
) -> list[str]:
    """What a patch changes, one short line per operation, for the variant card.

    scopes (component id -> data scope, see templates.render.component_scopes): a static
    change to a component drawn once per list item is marked, since it changes every item.
    labels (see item_labels): unrolled copies are named by the item they show.
    """
    scopes = scopes or {}
    labels = labels or {}
    lines = []
    for op in patch:
        parts = op["path"].split("/")[2:]  # after "", "components"
        raw = parts[0].replace("~1", "/").replace("~0", "~") if parts else "?"
        cid = f"{raw} ({labels[raw]})" if raw in labels else raw
        where = ".".join("end" if p == "-" else p for p in parts[1:])
        value = op.get("value")
        scope = scopes.get(raw, "")
        bound = isinstance(value, dict) and set(value) == {"path"}
        every = f" (applies to every item in {scope.removesuffix('/*')})" if scope and where and not bound and op["op"] != "test" else ""
        if op["op"] == UNROLL:
            lines.append(f"{cid}: split into one copy per item (fixed to the items shown now)")
            continue
        if not where:
            kind = f" ({value['component']})" if isinstance(value, dict) and "component" in value else ""
            verb = {"add": "added", "remove": "removed", "replace": "replaced", "move": "moved", "copy": "copied"}.get(op["op"])
            if verb:
                lines.append(f"{verb} {cid}{kind}")
            continue
        if op["op"] == "test":
            continue
        shown = value if isinstance(value, str) else None
        tail = f' → "{shown}"' if shown is not None and len(shown) <= 40 else ""
        verb = {"add": "added", "remove": "removed", "replace": "changed", "move": "moved", "copy": "copied"}[op["op"]]
        lines.append(f"{cid}.{where}: {verb}{tail}{every}")
    return lines
