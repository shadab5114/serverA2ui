"""Sanity-check (and lightly repair) the component graph the LLM produced (reference: src/validateGraph.js).

The renderer builds the UI by walking `child`/`children` references from the
component with id "root". A component never referenced from root is an ORPHAN
and renders nothing; a root whose `children` is a bare `{path}` binding with no
seeded data comes up blank. This catches those cases and, where possible,
repairs them IN PLACE so the UI still renders.

Only `child` and `children` create child components in this catalog, so
reachability is defined purely by them. tests/test_graph_check.py replays
fixtures recorded from the Node implementation before it was retired.
"""

from __future__ import annotations

import json
from typing import Any


def _js_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _is_template_children(comp: dict) -> bool:
    ch = comp.get("children")
    return isinstance(ch, dict) and isinstance(ch.get("componentId"), str)


def _refs_of(comp: dict) -> tuple[list[str], list[str]]:
    """Ids a component references as children.

    hard: shapes that are unambiguously references (must exist).
    soft: a single string `children`, a reference only if it names a known
          component (otherwise it is text content, e.g. a Button label).
    """
    hard: list[str] = []
    soft: list[str] = []
    if isinstance(comp.get("child"), str):
        hard.append(comp["child"])
    ch = comp.get("children")
    if isinstance(ch, list):
        for v in ch:
            if isinstance(v, str):
                hard.append(v)
            elif isinstance(v, dict) and isinstance(v.get("id"), str):
                hard.append(v["id"])
    elif _is_template_children(comp):
        hard.append(ch["componentId"])  # list template
    elif isinstance(ch, str):
        soft.append(ch)
    return hard, soft


def validate_and_repair_graph(doc: Any) -> dict[str, Any]:
    """Returns {repaired, warnings, errors}; may rewrite root's children in place."""
    warnings: list[str] = []
    errors: list[str] = []
    repaired = False

    messages = doc.get("a2ui") if isinstance(doc, dict) else None
    components: list[Any] = []
    for m in messages if isinstance(messages, list) else []:
        lst = m.get("updateComponents", {}).get("components") if isinstance(m, dict) else None
        if isinstance(lst, list):
            components.extend(lst)

    if not components:
        errors.append("No components found (no updateComponents.components).")
        return {"repaired": repaired, "warnings": warnings, "errors": errors}

    by_id: dict[str, dict] = {}
    for c in components:
        if not isinstance(c, dict) or not isinstance(c.get("id"), str):
            errors.append(f'A component is missing a string "id": {_js_json(c)}.')
            continue
        if c["id"] in by_id:
            errors.append(f'Duplicate component id "{c["id"]}".')
        by_id[c["id"]] = c

    comps = [c for c in components if isinstance(c, dict)]

    # Referenced set + dangling detection.
    referenced: set[str] = set()
    for c in comps:
        hard, soft = _refs_of(c)
        for ref in hard:
            if ref in by_id:
                referenced.add(ref)
            else:
                cid = c.get("id", "undefined")  # JS interpolates a missing id as "undefined"
                errors.append(f'Component "{cid}" references missing child id "{ref}".')
        for ref in soft:
            if ref in by_id:
                referenced.add(ref)

    roots = [c for c in comps if c.get("id") == "root"]
    if not roots:
        errors.append('No component has id "root" — the tree has no entry point.')
        return {"repaired": repaired, "warnings": warnings, "errors": errors}
    if len(roots) > 1:
        errors.append('More than one component has id "root".')
    root = roots[0]

    # Orphans: non-root components nothing references.
    orphans = [
        c["id"] for c in comps
        if c.get("id") != "root" and isinstance(c.get("id"), str) and c["id"] not in referenced
    ]

    if orphans:
        if _is_template_children(root):
            # Root drives a dynamic list template; static orphans can't safely be
            # folded into it. Report rather than guess.
            warnings.append(
                f"Orphan components not attached (root uses a list template): {', '.join(orphans)}."
            )
        else:
            # Rebuild root.children as an explicit array: existing valid refs + orphans.
            existing: list[str] = []
            if isinstance(root.get("child"), str) and root["child"] in by_id:
                existing.append(root.pop("child"))
            rch = root.get("children")
            if isinstance(rch, list):
                existing.extend(v for v in rch if isinstance(v, str) and v in by_id)
            elif isinstance(rch, str) and rch in by_id:
                existing.append(rch)
            # A useless binding (e.g. {"path": "form"}) is simply dropped here.
            root["children"] = list(dict.fromkeys([*existing, *orphans]))
            repaired = True
            warnings.append(f"Attached {len(orphans)} orphan component(s) to root: {', '.join(orphans)}.")

    return {"repaired": repaired, "warnings": warnings, "errors": errors}
