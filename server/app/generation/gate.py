"""Validator gate: generated A2UI components vs the design system's catalog.json.

Replaces Node's Zod-based src/catalogSchemas.js, and the semantics change on
purpose (PYTHON-BACKEND-PLAN.md, gotchas 1-3):
  - catalog.json describes the WIRE format: dynamic props are DynamicString /
    DynamicBoolean / ..., which accept `{"path": ...}` bindings natively, so no
    binding-aware hack is needed.
  - Every component declares `unevaluatedProperties: false`, so undeclared props
    are REJECTED (Zod ignored them). `action`, `checks` and `weight` are declared
    in $defs/CatalogComponentCommon, so interactivity still validates.
  - Borrowed layout components (Column/Row/List/Divider) aren't in catalog.json:
    reported in `unknownComponents`, not validated (same as Node).

Return shapes match Node: validate_component -> {ok, component, id, issues, unknown};
validate_a2ui_document -> {valid, checked, unknownComponents, failures}.
"""

from __future__ import annotations

from functools import cache
from typing import Any

from jsonschema import Draft202012Validator, ValidationError

from ..grounding.catalog import load_catalog


@cache
def _validator(component: str) -> Draft202012Validator | None:
    catalog = load_catalog()
    schema = catalog["components"].get(component)
    if schema is None:
        return None
    # Every $ref in catalog.json is local (#/$defs/...), so bundling $defs is enough.
    return Draft202012Validator({"$defs": catalog["defs"], **schema})


def known_components() -> list[str]:
    return list(load_catalog()["components"])


@cache
def _declared_props(component: str) -> frozenset[str]:
    """Every property name the component's schema declares (across allOf/oneOf/anyOf and local $refs)."""
    catalog = load_catalog()
    names: set[str] = set()
    seen: set[str] = set()

    def walk(schema: Any) -> None:
        if not isinstance(schema, dict):
            return
        ref = schema.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/$defs/") and ref not in seen:
            seen.add(ref)
            walk(catalog["defs"].get(ref.removeprefix("#/$defs/")))
        names.update(schema.get("properties") or {})
        for key in ("allOf", "oneOf", "anyOf"):
            for sub in schema.get(key) or []:
                walk(sub)

    walk(catalog["components"][component])
    return frozenset(names)


def _undeclared_issue(component: str, node: dict) -> str | None:
    """Rewrite jsonschema's unevaluatedProperties error to list only truly undeclared props.

    Per the spec, a FAILED allOf branch drops its annotations, so one bad enum
    makes every prop of that branch "unevaluated" too. Sending that to the repair
    prompt would mislead the model, so report only props the schema never declares.
    """
    extra = [k for k in node if k not in _declared_props(component)]
    if not extra:
        return None
    listed = ", ".join(repr(k) for k in extra)
    verb = "was" if len(extra) == 1 else "were"
    return f"(root): Unevaluated properties are not allowed ({listed} {verb} unexpected)"


def _leaf_errors(error: ValidationError):
    """jsonschema nests branch failures (oneOf/anyOf) under .context; the leaves say what's wrong."""
    if error.context:
        for sub in error.context:
            yield from _leaf_errors(sub)
    else:
        yield error


def _format(error: ValidationError) -> str:
    path = ".".join(str(p) for p in error.absolute_path) or "(root)"
    return f"{path}: {error.message}"


def validate_component(node: Any) -> dict[str, Any]:
    """Validate one A2UI component object (the WHOLE node: id, component, props)."""
    node_id = node.get("id") if isinstance(node, dict) else None
    node_id = "<no id>" if node_id is None else node_id
    component = node.get("component") if isinstance(node, dict) else None
    if not component or not isinstance(component, str):
        name = "undefined" if component is None else str(component)
        return {"ok": False, "component": name, "id": node_id, "unknown": False, "issues": ["missing 'component' name"]}

    validator = _validator(component)
    if validator is None:
        # Not a pds component (e.g. borrowed layout Column/Row/List/Divider): can't
        # validate it here, but it's not necessarily invalid.
        return {"ok": True, "component": component, "id": node_id, "unknown": True, "issues": []}

    issues: list[str] = []
    for err in sorted(validator.iter_errors(node), key=lambda e: list(map(str, e.absolute_path))):
        for leaf in _leaf_errors(err):
            if leaf.validator == "unevaluatedProperties" and not leaf.absolute_path:
                msg = _undeclared_issue(component, node)
            else:
                msg = _format(leaf)
            if msg and msg not in issues:
                issues.append(msg)
    return {"ok": not issues, "component": component, "id": node_id, "unknown": False, "issues": issues}


def validate_a2ui_document(doc: Any) -> dict[str, Any]:
    """Validate every component in every updateComponents message ({a2ui: [...]} or a bare list)."""
    if isinstance(doc, list):
        messages = doc
    elif isinstance(doc, dict) and isinstance(doc.get("a2ui"), list):
        messages = doc["a2ui"]
    else:
        messages = []

    failures: list[dict[str, Any]] = []
    unknown: list[str] = []
    checked = 0
    for msg in messages:
        comps = msg.get("updateComponents", {}).get("components") if isinstance(msg, dict) else None
        if not isinstance(comps, list):
            continue
        for node in comps:
            r = validate_component(node)
            if r["unknown"]:
                if r["component"] not in unknown:
                    unknown.append(r["component"])
            else:
                checked += 1
                if not r["ok"]:
                    failures.append({"id": r["id"], "component": r["component"], "issues": r["issues"]})

    return {"valid": not failures, "checked": checked, "unknownComponents": unknown, "failures": failures}
