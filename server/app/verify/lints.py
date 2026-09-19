"""Hard rules as deterministic lints (the guideline gate's first half, P7).

Each rule's TEXT lives in guidelines/hard-rules.md ("## DS-1xx · Title"); its CHECK
lives here, keyed by the same id. tests/test_verify.py fails if the two drift apart.
Violations go back to the generator's repair loop with the rule's id, title and text.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

from ..grounding.sources import LocalGuidelines, Source

_PRICE = re.compile(r"[$€£]\s?\d")
_SKIP_TEXT_KEYS = {"id", "component", "href", "src", "action", "checks"}
_LABELLED = ("InputField", "TextArea", "CheckboxGroup", "RadioButtonGroup")


@dataclass(frozen=True)
class Violation:
    rule_id: str
    component_ids: tuple[str, ...]
    detail: str

    def message(self, rule: Source | None) -> str:
        where = f" (component {', '.join(self.component_ids)})" if self.component_ids else ""
        head = f"Guideline {rule.cite()}" if rule else f"Guideline [{self.rule_id}]"
        text = f" Rule: {' '.join(rule.text.split())}" if rule else ""
        return f"{head}{where}: {self.detail}.{text}"


@dataclass
class Surface:
    """The components of one A2UI document, plus which ones render once per list item."""

    components: list[dict[str, Any]]
    repeated: set[str]

    @classmethod
    def of(cls, doc: Any) -> Surface:
        comps: list[dict[str, Any]] = []
        for m in (doc.get("a2ui") if isinstance(doc, dict) else doc) or []:
            if isinstance(m, dict):
                comps.extend(c for c in m.get("updateComponents", {}).get("components", []) if isinstance(c, dict))
        by_id = {c["id"]: c for c in comps if isinstance(c.get("id"), str)}
        repeated: set[str] = set()

        def mark(cid: str, inside: bool, seen: set[str]) -> None:
            if cid in seen or cid not in by_id:
                return
            seen.add(cid)
            if inside:
                repeated.add(cid)
            comp = by_id[cid]
            ch = comp.get("children")
            if isinstance(ch, dict) and isinstance(ch.get("componentId"), str):
                mark(ch["componentId"], True, seen)
            elif isinstance(ch, list):
                for v in ch:
                    if isinstance(v, str):
                        mark(v, inside, seen)
            elif isinstance(ch, str):
                mark(ch, inside, seen)
            if isinstance(comp.get("child"), str):
                mark(comp["child"], inside, seen)

        mark("root", False, set())
        return cls(comps, repeated)

    def of_type(self, *names: str) -> Iterator[dict[str, Any]]:
        return (c for c in self.components if c.get("component") in names)


def _static_strings(value: Any, key: str = "") -> Iterator[tuple[str, str]]:
    """(key, text) for every literal string under a prop value; bindings and actions are skipped."""
    if key in _SKIP_TEXT_KEYS:
        return
    if isinstance(value, str):
        yield key, value
    elif isinstance(value, dict):
        if set(value) == {"path"}:
            return  # a binding: the value comes from data
        for k, v in value.items():
            yield from _static_strings(v, k)
    elif isinstance(value, list):
        for v in value:
            yield from _static_strings(v, key)


def _is_blank(v: Any) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


# --- the rules ------------------------------------------------------------------

def ds_101(s: Surface) -> list[Violation]:
    primaries = [c["id"] for c in s.of_type("Button") if c.get("kind", "primary") == "primary"]
    for group in s.of_type("ButtonGroup"):
        n = sum(1 for it in group.get("items") or [] if isinstance(it, dict) and it.get("kind") == "primary")
        primaries += [group["id"]] * n
    out = []
    repeated = sorted({cid for cid in primaries if cid in s.repeated})
    if repeated:
        out.append(Violation("DS-101", tuple(repeated), "a primary button inside a repeated list item renders once per item"))
    if len(primaries) > 1:
        out.append(Violation("DS-101", tuple(dict.fromkeys(primaries)), f"{len(primaries)} primary buttons on one surface"))
    return out


def ds_102(s: Surface) -> list[Violation]:
    missing = [c["id"] for c in s.of_type(*_LABELLED) if _is_blank(c.get("label"))]
    return [Violation("DS-102", tuple(missing), "input without a label")] if missing else []


def ds_103(s: Surface) -> list[Violation]:
    texts = []
    for c in s.of_type("Badge"):
        texts.append((c["id"], c.get("children")))
    for c in s.of_type("ComposableTileContainer"):
        texts.append((c["id"], (c.get("cap") or {}).get("children")))
    for c in s.of_type("Tilelet"):
        texts.append((c["id"], (c.get("badge") or {}).get("children")))
    long = [(cid, t) for cid, t in texts if isinstance(t, str) and (len(t) > 24 or len(t.split()) > 3)]
    return [Violation("DS-103", (cid,), f'badge text "{t}" is too long') for cid, t in long]


def ds_104(s: Surface) -> list[Violation]:
    missing = [c["id"] for c in s.of_type("Image") if _is_blank(c.get("alt"))]
    return [Violation("DS-104", tuple(missing), "image without alt text")] if missing else []


def ds_105(s: Surface) -> list[Violation]:
    out = []
    for c in s.components:
        for key, text in _static_strings({k: v for k, v in c.items() if k not in _SKIP_TEXT_KEYS}):
            if _PRICE.search(text):
                out.append(Violation("DS-105", (c.get("id", "?"),), f'literal price in {key or "text"}: "{text}"'))
    return out


LINTS: dict[str, Callable[[Surface], list[Violation]]] = {
    "DS-101": ds_101,
    "DS-102": ds_102,
    "DS-103": ds_103,
    "DS-104": ds_104,
    "DS-105": ds_105,
}


def lint_document(doc: Any) -> list[Violation]:
    surface = Surface.of(doc)
    return [v for check in LINTS.values() for v in check(surface)]


def lint_messages(doc: Any, guidelines: LocalGuidelines | None = None) -> tuple[list[str], list[Violation]]:
    """Violations as repair-prompt lines (quoting the rule text) plus the raw violations."""
    guidelines = guidelines or LocalGuidelines()
    violations = lint_document(doc)
    return [v.message(guidelines.get(v.rule_id)) for v in violations], violations
