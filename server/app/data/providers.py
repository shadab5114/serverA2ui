"""Data providers: the ONLY source of values in a template (plan names, prices, features).

The LLM chooses a provider's params, never its values. Each provider declares:
  - params: what DECIDE may pass (typed; coerced here, unknown ones dropped)
  - fields: every JSON Pointer its output can contain ("*" = any array index).
    Templates may bind only to these (enforced by tests/test_templates.py), and
    P8 variants will be held to the same contract.
Reads illustrative mock JSON from DATA_DIR; a real API can replace a reader later.

Providers written here are "code providers". Most use cases don't need one: a
provider can be declared as data in PROVIDERS_DIR (see declared.py), and REGISTRY
serves both kinds side by side.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

from ..config import settings


class ProviderError(ValueError):
    pass


@dataclass(frozen=True)
class Param:
    name: str
    type: str  # "string" | "number" | "boolean"
    description: str
    required: bool = False
    choices: Callable[[], list[str]] | None = None  # allowed string values, for the DECIDE prompt


@dataclass(frozen=True)
class Provider:
    name: str
    description: str
    params: list[Param]
    fields: frozenset[str]
    read: Callable[[dict[str, Any]], dict[str, Any]] = field(repr=False)
    cases: tuple[dict[str, Any], ...] = ()  # param sets that exercise every param (declared providers derive them)
    origin: str = "code"  # where it's defined: "code", or the declaration's data file

    def describe(self) -> str:
        """One-line-per-param description for the DECIDE prompt."""
        lines = [f"{self.name}: {self.description}"]
        for p in self.params:
            choice = f" One of: {', '.join(p.choices())}." if p.choices else ""
            need = "required" if p.required else "optional"
            lines.append(f"  - {p.name} ({p.type}, {need}): {p.description}{choice}")
        return "\n".join(lines)

    def call(self, raw: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.read(self.coerce(raw or {}))

    def coerce(self, raw: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for p in self.params:
            v = raw.get(p.name)
            if v is None or v == "":
                if p.required:
                    raise ProviderError(f"{self.name}: missing required param {p.name!r}")
                continue
            out[p.name] = _coerce(p, v)
        return out


def _coerce(p: Param, v: Any) -> Any:
    try:
        if p.type == "number":
            return float(str(v).replace("$", "").replace(",", "").strip())
        if p.type == "boolean":
            return v if isinstance(v, bool) else str(v).strip().lower() in ("true", "yes", "1")
    except ValueError as err:
        raise ProviderError(f"param {p.name!r}: {v!r} is not a {p.type}") from err
    v = str(v)
    if p.choices:
        allowed = p.choices()
        match = next((c for c in allowed if c.casefold() == v.strip().casefold()), None)
        if match is None:
            raise ProviderError(f"param {p.name!r}: {v!r} is not one of {allowed}")
        return match
    return v


@cache
def _load(filename: str, data_dir: Path) -> dict[str, Any]:
    return json.loads((data_dir / filename).read_text(encoding="utf-8"))


def _plans() -> list[dict]:
    return _load("plans.json", settings.data_dir)["plans"]


def _addons() -> list[dict]:
    return _load("addons.json", settings.data_dir)["addons"]


def _money(n: float) -> str:
    return f"${n:g}"


# --- plans.list ---------------------------------------------------------------

def _plans_list(params: dict[str, Any]) -> dict[str, Any]:
    plans = _plans()
    shown = [
        p for p in plans
        if ("maxPrice" not in params or p["priceMonthly"] <= params["maxPrice"])
        and (not params.get("unlimitedOnly") or p["unlimited"])
    ]
    filters = []
    if params.get("unlimitedOnly"):
        filters.append("unlimited data")
    if "maxPrice" in params:
        filters.append(f"up to {_money(params['maxPrice'])}/mo")
    if not shown:
        summary = f"No plans match {' and '.join(filters)}. Try a higher budget."
    elif filters:
        summary = f"{len(shown)} of {len(plans)} plans with {' and '.join(filters)}."
    else:
        summary = f"All {len(plans)} plans. Prices are per line, per month."
    return {
        "summary": summary,
        "plans": [
            {
                "id": p["id"],
                "name": p["name"],
                "badge": p["badge"],
                "priceMonthly": p["priceMonthly"],
                "priceLabel": f"{_money(p['priceMonthly'])}/mo",
                "unlimited": p["unlimited"],
                "dataLabel": "Unlimited data" if p["unlimited"] else f"{p['dataGb']} GB data",
                "hotspotLabel": f"{p['hotspotGb']} GB hotspot" if p["hotspotGb"] else "No hotspot",
                "features": [{"text": f} for f in p["features"]],
            }
            for p in shown
        ],
    }


PLANS_LIST = Provider(
    name="plans.list",
    description="The mobile plans on offer, cheapest first, optionally filtered.",
    params=[
        Param("maxPrice", "number", "Only plans at or below this monthly price in dollars."),
        Param("unlimitedOnly", "boolean", "Only plans with unlimited data."),
    ],
    fields=frozenset({
        "/summary", "/plans",
        "/plans/*/id", "/plans/*/name", "/plans/*/badge", "/plans/*/priceMonthly", "/plans/*/priceLabel",
        "/plans/*/unlimited", "/plans/*/dataLabel", "/plans/*/hotspotLabel",
        "/plans/*/features", "/plans/*/features/*/text",
    }),
    read=_plans_list,
)


# --- addons.list --------------------------------------------------------------

def _plan_ids() -> list[str]:
    return [p["id"] for p in _plans()]


def _addons_list(params: dict[str, Any]) -> dict[str, Any]:
    plan = next((p for p in _plans() if p["id"] == params.get("planId")), None)
    addons = [
        a for a in _addons()
        if plan is None or a["availableFor"] == "all" or plan["id"] in a["availableFor"]
    ]
    return {
        "planId": plan["id"] if plan else "",
        "heading": f"Add-ons for {plan['name']}" if plan else "Add-ons",
        "summary": (
            f"{len(addons)} add-ons work with {plan['name']}. Pick any you'd like."
            if plan else f"{len(addons)} add-ons. Availability depends on your plan."
        ),
        "addons": [
            {
                "id": a["id"],
                "name": a["name"],
                "priceLabel": a["priceLabel"],
                "detail": f"{a['description']} · {a['priceLabel']}",
                "selected": False,
            }
            for a in addons
        ],
    }


ADDONS_LIST = Provider(
    name="addons.list",
    description="Optional add-ons, limited to those available for one plan when planId is given.",
    params=[Param("planId", "string", "The plan to show add-ons for.", choices=_plan_ids)],
    fields=frozenset({
        "/planId", "/heading", "/summary", "/addons",
        "/addons/*/id", "/addons/*/name", "/addons/*/priceLabel", "/addons/*/detail", "/addons/*/selected",
    }),
    read=_addons_list,
)


class ProviderRegistry(Mapping[str, Provider]):
    """The code providers above plus the declared ones (declared.py) in PROVIDERS_DIR.

    Declarations and data files are re-read when they change, so a new use case shows
    up without a restart (like templates). A broken declaration is left out and listed
    in `errors` (printed once, and failed by the tests), never fatal to the server.
    """

    def __init__(self, code: Iterable[Provider], dirs: Callable[[], tuple[Path, Path]]) -> None:
        self._code = {p.name: p for p in code}
        self._dirs = dirs  # () -> (providers dir, data dir)
        self._seen: tuple[Any, ...] | None = None
        self._all: dict[str, Provider] = dict(self._code)
        self.errors: list[str] = []

    def _current(self) -> dict[str, Provider]:
        providers_dir, data_dir = self._dirs()
        files = sorted({*providers_dir.glob("*.json"), *data_dir.rglob("*.json")})
        seen = tuple((str(f), f.stat().st_mtime_ns, f.stat().st_size) for f in files if f.is_file())
        if seen != self._seen:
            from .declared import load_declared

            declared, errors = load_declared(providers_dir, data_dir, taken=set(self._code))
            self._all = {**self._code, **{p.name: p for p in declared}}
            for err in sorted(set(errors) - set(self.errors)):
                print(f"  provider declaration skipped: {err}", flush=True)
            self.errors, self._seen = errors, seen
        return self._all

    def __getitem__(self, name: str) -> Provider:
        return self._current()[name]

    def __iter__(self) -> Iterator[str]:
        return iter(self._current())

    def __len__(self) -> int:
        return len(self._current())


REGISTRY = ProviderRegistry((PLANS_LIST, ADDONS_LIST), lambda: (settings.providers_dir, settings.data_dir))


def pointer_patterns(value: Any, base: str = "") -> set[str]:
    """Every pointer in a data object, array indices written as '*' (a field schema read off real data).

    An array item that is itself an object or list ('/plans/*') is only a container
    for its fields, so it isn't listed; scalar items ('/tags/*') are.
    """
    container_item = base.endswith("/*") and isinstance(value, (dict, list))
    out = {base} if base and not container_item else set()
    if isinstance(value, dict):
        for k, v in value.items():
            out |= pointer_patterns(v, f"{base}/{k}")
    elif isinstance(value, list):
        for v in value:
            out |= pointer_patterns(v, f"{base}/*")
    return out


def field_matches(fields: frozenset[str], pointer: str) -> bool:
    """Is a concrete or pattern pointer ('/plans/2/name', '/plans/*/name') one of a provider's declared fields?"""
    return re.sub(r"/\d+(?=/|$)", "/*", pointer) in fields


def get_provider(name: str) -> Provider:
    try:
        return REGISTRY[name]
    except KeyError as err:
        raise ProviderError(f"unknown data provider {name!r}") from err
