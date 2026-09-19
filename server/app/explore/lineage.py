"""Lineage: what's on screen in a thread and how each surface was made (P8).

Kept in graph state (so the checkpointer persists it) as `surfaces`, one record per
surface the thread has shown, each with the surface as it stands now (`doc`):

    "baseline-1": {"kind": "baseline", "templateId": "plan-tiles", "version": 1, "params": {}, "patches": [], "doc": {...}}
    "var-2":      {"kind": "variant", "templateId": "plan-tiles", "version": 1, "params": {}, "from": "baseline-1",
                   "patches": [[...rev 1 ops...], [...rev 2 ops...]], "doc": {...},
                   "title": ..., "rationale": ..., "sources": [...], "missingData": [...]}
    "ui-1":       {"kind": "generated", "patches": [], "doc": {...}, "title": ...}

REFINE modifies the target's `doc` (the whole screen goes to the model, see
modify.py) and appends what changed to `patches`; other surfaces are untouched.
Refining a baseline starts a new variant (production itself is never edited).
`last_surface` in state names the surface shown most recently: the default target.
"""

from __future__ import annotations

import re
from typing import Any

from ..data.providers import get_provider
from ..templates.render import render_template
from ..templates.store import TemplateStore
from .patching import apply_chain
from .variants import Screen

_NUM = re.compile(r"-(\d+)$")
_PREFIX = {"variant": "var", "baseline": "baseline", "generated": "ui"}


def next_id(surfaces: dict[str, Any], kind: str) -> str:
    prefix = _PREFIX[kind]
    taken = [int(m.group(1)) for sid in surfaces if sid.startswith(prefix + "-") and (m := _NUM.search(sid))]
    return f"{prefix}-{max(taken, default=0) + 1}"


def baseline_record(
    template_id: str, version: int, params: dict[str, Any], title: str, doc: dict[str, Any] | None = None
) -> dict[str, Any]:
    return {"kind": "baseline", "templateId": template_id, "version": version, "params": dict(params),
            "patches": [], "title": title, **({"doc": doc} if doc is not None else {})}


def generated_record(doc: dict[str, Any], title: str) -> dict[str, Any]:
    return {"kind": "generated", "patches": [], "title": title, "doc": doc}


def ref(record: dict[str, Any]) -> str:
    return f"{record['templateId']}@{record['version']}" if record.get("templateId") else "generated UI"


def rev(record: dict[str, Any]) -> int:
    """Variants count from their first patch; generated UI is rev 1 as made; a baseline never changes."""
    if record["kind"] == "baseline":
        return 0
    return len(record["patches"]) + (1 if record["kind"] == "generated" else 0)


def label(surface_id: str, record: dict[str, Any]) -> str:
    """How a card is titled: "Baseline · plan-tiles@1", "Variant 2 · rev 3", "Generated 1 · rev 2"."""
    if record["kind"] == "baseline":
        return f"Baseline · {ref(record)}"
    n = surface_id.split("-")[-1]
    name = "Generated" if record["kind"] == "generated" else "Variant"
    return f"{name} {n}" + (f" · rev {rev(record)}" if rev(record) > 1 else "")


def rebuild(record: dict[str, Any], store: TemplateStore) -> tuple[Screen, list[str]]:
    """A template-based surface rebuilt as template + data + patches, plus notes (e.g. a newer template version)."""
    template = store.get(record["templateId"])
    notes = []
    if template.manifest.version != record["version"]:
        notes.append(f"{record['templateId']} is now v{template.manifest.version}; this surface was built on "
                     f"v{record['version']} and is rebuilt on the current one")
    doc = render_template(template, record.get("params") or {})["a2ui"]
    doc = apply_chain(doc, record["patches"])
    return Screen(doc, get_provider(template.manifest.provider), ref(record)), notes


def current_doc(record: dict[str, Any], store: TemplateStore) -> tuple[dict[str, Any], list[str]]:
    """The surface as it stands now: its stored doc, or (older records) a rebuild."""
    if isinstance(record.get("doc"), dict):
        return record["doc"], []
    screen, notes = rebuild(record, store)
    return screen.doc, notes


def screen_lines(surfaces: dict[str, Any], latest: str | None = None) -> list[str]:
    """What's on screen, for DECIDE: one line per surface; the latest is marked (the default REFINE target)."""
    lines = []
    for sid, r in surfaces.items():
        mark = " [latest]" if sid == latest else ""
        if r["kind"] == "baseline":
            lines.append(f'{sid}{mark} (card "{label(sid, r)}"): "{r.get("title", r["templateId"])}", the unchanged production screen')
        elif r["kind"] == "generated":
            lines.append(f'{sid}{mark} (card "{label(sid, r)}"): generated UI for "{r.get("title", "")}"')
        else:
            n = sid.split("-")[-1]
            lines.append(f'{sid}{mark} (card "{label(sid, r)}", a.k.a. option {n}): variant "{r.get("title", "")}" of {ref(r)}: '
                         f'{r.get("rationale", "")}')
    return lines
