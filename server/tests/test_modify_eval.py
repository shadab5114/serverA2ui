"""Modify accuracy + latency on NON-plan screens, against the REAL model (on demand only):

    uv run pytest -m eval tests/test_modify_eval.py -s

Every check is code, not a model: did the change pass the gate, did exactly the right
list items change, were no data values copied into literal text, and did only the asked-for
components change. The printed table is the accuracy/latency baseline to compare changes against.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any, Callable

import pytest

from app.explore.modify import ModifyResult, modify
from app.explore.patching import _data_model, to_view, unroll
from evals.modify_cases import SCREENS

pytestmark = [pytest.mark.eval, pytest.mark.asyncio(loop_scope="module")]
REPORT: list[tuple[str, bool, int, float, str]] = []


# --- checks ---------------------------------------------------------------------------

def comps(doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return to_view(doc)["components"]


def _norm(body: dict[str, Any]) -> str:
    return json.dumps({k: v for k, v in body.items() if k not in ("child", "children") or isinstance(v, dict)
                       and "componentId" not in v}, sort_keys=True)


def _bound_index(body: dict[str, Any], list_path: str) -> int | None:
    m = re.search(rf'"{re.escape(list_path)}/(\d+)(?:/|")', json.dumps(body))
    return int(m.group(1)) if m else None


def changed_items(base: dict[str, Any], after: dict[str, Any], container: str, list_path: str) -> set[int]:
    """Which list items look different from what a plain split of the base would give (by their bound components)."""
    split = unroll(to_view(base), _data_model(base), container)["components"]

    def groups(view: dict[str, Any]) -> dict[int, list[str]]:
        out: dict[int, list[str]] = {}
        for body in view.values():
            i = _bound_index(body, list_path)
            if i is not None:
                out.setdefault(i, []).append(_norm(body))
        return {i: sorted(v) for i, v in out.items()}

    before, now = groups(split), groups(comps(after))
    return {i for i in set(before) | set(now) if before.get(i) != now.get(i)}


def copied_data(base: dict[str, Any], after: dict[str, Any], request: str = "") -> list[str]:
    """New literal strings that equal a data value: data written as text instead of bound.
    Words the user asked for are UI copy, not copied data ("highlight the delayed orders" -> a "Delayed" badge)."""
    values: set[str] = set()

    def collect(v: Any) -> None:
        if isinstance(v, str) and len(v) >= 3:
            values.add(v.lower())
        elif isinstance(v, dict):
            for x in v.values():
                collect(x)
        elif isinstance(v, list):
            for x in v:
                collect(x)

    collect(_data_model(base))
    old = json.dumps(comps(base))
    out = []

    def strings(v: Any, key: str = ""):
        if isinstance(v, str) and key not in ("id", "component", "path", "componentId"):
            yield v
        elif isinstance(v, dict):
            for k, x in v.items():
                yield from strings(x, k)
        elif isinstance(v, list):
            for x in v:
                yield from strings(x, key)

    for s in strings(comps(after)):
        if s.lower() in values and json.dumps(s) not in old and s.lower() not in request.lower():
            out.append(s)
    return out


def touched(r: ModifyResult) -> set[str]:
    return {op["path"].split("/")[2] for op in r.patch}


Check = Callable[[dict[str, Any], ModifyResult], str | None]  # returns why it's wrong, or None


def only(*ids: str) -> Check:
    return lambda base, r: None if touched(r) <= set(ids) else f"touched more than {ids}: {sorted(touched(r))}"


def items(container: str, path: str, want: set[int]) -> Check:
    def check(base, r):
        got = changed_items(base, r.doc, container, path)
        return None if got == want else f"changed items {sorted(got)}, wanted {sorted(want)}"
    return check


def prop(cid: str, key: str, value: Any) -> Check:
    def check(base, r):
        c = comps(r.doc).get(cid, {})
        got = c
        for k in key.split("."):
            got = got.get(k) if isinstance(got, dict) else None
        return None if got == value else f"{cid}.{key} = {got!r}, wanted {value!r}"
    return check


def all_of(*checks: Check) -> Check:
    def check(base, r):
        return next((why for c in checks if (why := c(base, r))), None)
    return check


def still_a_list(container: str) -> Check:
    return lambda base, r: None if isinstance(comps(r.doc)[container].get("children"), dict) else f"{container} was split"


def new_toggle_between(after_id: str, before_id: str) -> Check:
    def check(base, r):
        c = comps(r.doc)
        root = c["root"]["children"]
        new = [cid for cid, b in c.items() if b["component"] == "Toggle" and cid not in comps(base)]
        if len(new) != 1:
            return f"expected one new Toggle, got {new}"
        path = (c[new[0]].get("checked") or {}).get("path")
        if not path or not isinstance(r.mod.new_state.get(path), bool):
            return f"new toggle binds {path!r}, newState {r.mod.new_state}"
        flat = json.dumps(root)
        pos = lambda cid: next((i for i, x in enumerate(root) if x == cid), None)  # noqa: E731
        holder = next((x for x in root if new[0] == x or new[0] in json.dumps(c.get(x, {}))), None)
        if holder is None or not pos(after_id) < pos(holder) < pos(before_id):
            return f"toggle placed wrong: root {flat}"
        return None
    return check


def removed(component: str, keep: set[str]) -> Check:
    def check(base, r):
        c = comps(r.doc)
        left = [cid for cid, b in c.items() if b["component"] == component]
        return None if not left and keep <= set(c) else f"{component} left: {left}; missing: {keep - set(c)}"
    return check


def root_order(want: list[str]) -> Check:
    return lambda base, r: None if comps(r.doc)["root"]["children"] == want else f"root order {comps(r.doc)['root']['children']}"


def new_text_after(anchor: str, text: str) -> Check:
    def check(base, r):
        c = comps(r.doc)
        root = c["root"]["children"]
        new = [cid for cid, b in c.items() if b["component"] == "Text" and b.get("children") == text]
        if not new or new[0] not in root or root.index(new[0]) != root.index(anchor) + 1:
            return f"no Text {text!r} right after {anchor}: root {root}"
        return None
    return check


CASES: list[tuple[str, str, Check]] = [
    ("orders", "highlight the delayed orders with a red badge", items("order-list", "/orders", {1, 3})),
    ("orders", "add a subtle shadow to every order card",
     all_of(still_a_list("order-list"), prop("order-card", "dropShadow", "subtle"))),
    ("orders", "change the heading to Recent orders", all_of(prop("heading", "children", "Recent orders"), only("heading"))),
    ("settings", "add a dark mode toggle below the email notifications toggle", new_toggle_between("notify-toggle", "save")),
    ("settings", "rename the Save button to Save changes", all_of(prop("save", "children", "Save changes"), only("save"))),
    ("settings", "remove the display name field", removed("InputField", {"title", "notify-toggle", "save"})),
    ("products", "put a Sale badge on the trail shoes", items("product-row", "/products", {1})),
    ("products", "move the heading below the products", root_order(["product-row", "heading"])),
    ("dashboard", "make the status notification a warning", all_of(prop("alert", "kind", "warning"), only("alert"))),
    ("dashboard", "add a line under latency saying Updated every minute", new_text_after("latency", "Updated every minute")),
    # the heaviest case: one of five rich tiles (the demo's curated screen), kept as the latency benchmark
    ("plans", "change the color of cap from black to red for the best value plan", items("plan-row", "/plans", {2})),
]


def _plans_screen() -> dict[str, Any]:
    from app.config import settings
    from app.templates.render import render_template
    from app.templates.store import FileTemplateStore

    return render_template(FileTemplateStore(settings.templates_dir).get("plan-tiles"), {})["a2ui"]


SCREENS = {**SCREENS, "plans": _plans_screen()}


@pytest.mark.parametrize("screen, request_text, check", CASES, ids=[f"{s}: {r[:40]}" for s, r, _ in CASES])
async def test_modify(screen, request_text, check):
    base = SCREENS[screen]
    t = time.monotonic()
    r = await modify(base, request_text)
    took = time.monotonic() - t
    why = None
    if not r.ok:
        why = f"not ok: blocked={r.blocked!r} errors={r.errors[:2]}"
    elif not r.patch:
        why = "nothing changed"
    else:
        copied = copied_data(base, r.doc, request_text)
        why = check(base, r) or (f"copied data as text: {copied}" if copied else None)
    REPORT.append((f"{screen}: {request_text}", why is None, r.attempts, took, why or ""))
    assert why is None, f"{why}\nsummary: {r.mod.summary if r.mod else None}\nchanges: {r.changes}"


def test_zz_report():
    if not REPORT:
        pytest.skip("no cases ran")
    passed = sum(ok for _, ok, *_ in REPORT)
    print(f"\n\nmodify eval: {passed}/{len(REPORT)} passed, "
          f"median {sorted(t for *_, t, _ in REPORT)[len(REPORT) // 2]:.1f}s, max {max(t for *_, t, _ in REPORT):.1f}s")
    for name, ok, attempts, took, why in REPORT:
        print(f"  {'PASS' if ok else 'FAIL'}  {took:5.1f}s  x{attempts}  {name}  {why}")
