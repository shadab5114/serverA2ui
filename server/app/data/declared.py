"""Declared data providers: a provider described as data, so a new use case needs no Python.

A file `<PROVIDERS_DIR>/<name>.json` (default `data/providers/`) names a data file and
the list in it, the params DECIDE may pass and how each one filters, optional computed
display fields, and summary sentences. Its field schema is read off the data it returns
(`pointer_patterns`), so templates and variants are held to what really exists.
Code providers (providers.py) remain for anything this can't express; one registry
holds both.

    {
      "name": "things.list",                  optional; must equal the file name without .json
      "description": "…",                     one line for the DECIDE prompt
      "source": {"file": "things.json", "list": "/things"},    the output key is the list's last segment
      "sort": {"by": "price", "order": "asc"},                 optional
      "params": {
        "<param>": {
          "type": "string" | "number" | "boolean",
          "description": "…", "required": false,
          "filter": {"op": "eq", "field": "tags/*"},   see OPS; "value" makes the param an on/off switch
          "choices": "data" | ["a", "b"],               allowed values; "data" = every value of the field
          "label": "under ${value:g}"                  how the active filter reads in the summary
        }
      },
      "computed": {"priceLabel": "${price:,.2f}", "parts/*/label": "{qty} × {name}"},
      "summary": {"all": "All {total} things.", "filtered": "{count} of {total} things {filters}.",
                  "empty": "No things {filters}."}
    }

Fields are pointers relative to one item; "*" means every element of an array, and a
filter passes when ANY value there matches. Text placeholders are `{field}` or
`{field:spec}`: a Python format spec for numbers, `date` or a strftime pattern for ISO
dates. The output is `{<list>: [...], "count": n, "summary": "..."}`.
"""

from __future__ import annotations

import copy
import json
import re
from collections.abc import Callable
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .providers import Param, Provider, ProviderError, pointer_patterns

OPS: dict[str, Callable[[Any, Any], bool]] = {
    "eq": lambda have, want: _same(have, want),
    "ne": lambda have, want: not _same(have, want),
    "lt": lambda have, want: _cmp(have, want) < 0,
    "lte": lambda have, want: _cmp(have, want) <= 0,
    "gt": lambda have, want: _cmp(have, want) > 0,
    "gte": lambda have, want: _cmp(have, want) >= 0,
    "contains": lambda have, want: str(want).casefold() in str(have).casefold(),
}
LIMIT = "limit"  # keeps the first N items (after sorting); needs no field
TYPES = ("string", "number", "boolean")
PLACEHOLDER = re.compile(r"\{([A-Za-z_][\w./-]*)(?::([^{}]*))?\}")


def _same(have: Any, want: Any) -> bool:
    if isinstance(have, str) and isinstance(want, str):
        return have.casefold() == want.casefold()
    if isinstance(have, bool) or isinstance(want, bool):
        return have is want or str(have).lower() == str(want).lower()
    return have == want


def _cmp(have: Any, want: Any) -> int:
    """Numbers compare as numbers, anything else as text (so ISO dates order correctly)."""
    if have is None:
        raise TypeError("no value")
    if isinstance(have, (int, float)) and not isinstance(have, bool):
        a, b = float(have), float(want)
    else:
        a, b = str(have), str(want)
    return (a > b) - (a < b)


def values_at(item: Any, field: str) -> list[Any]:
    """The values at an item-relative pointer ("tags/*", "parts/*/name"); [] when absent."""
    found = [item]
    for key in [k for k in field.strip("/").split("/") if k]:
        nxt: list[Any] = []
        for v in found:
            if key == "*" and isinstance(v, list):
                nxt.extend(v)
            elif isinstance(v, dict) and key in v:
                nxt.append(v[key])
        found = nxt
    return [v for v in found if not isinstance(v, (dict, list))]


def _objects_at(item: Any, parent: str) -> list[dict[str, Any]]:
    """The objects a computed field is written into: the item itself, or those under a pointer."""
    found = [item]
    for key in [k for k in parent.strip("/").split("/") if k]:
        found = [x for v in found for x in (v if key == "*" and isinstance(v, list) else
                                            [v[key]] if isinstance(v, dict) and key in v else [])]
    return [v for v in found if isinstance(v, dict)]


def fill(text: str, values: dict[str, Any]) -> str:
    """Replace {name} / {name:spec} with values; a name the values lack becomes ""."""

    def one(m: re.Match[str]) -> str:
        name, spec = m.group(1), m.group(2)
        return _format(values[name], spec) if name in values else ""

    return PLACEHOLDER.sub(one, text)


def _format(value: Any, spec: str | None) -> str:
    if value is None:
        return ""
    if not spec:
        return f"{value:g}" if isinstance(value, float) else str(value)
    if isinstance(value, str):
        when = _as_date(value)
        if when is None:
            return format(value, spec)
        return f"{when:%b} {when.day}, {when.year}" if spec == "date" else when.strftime(spec)
    return format(value, spec)


def _as_date(text: str) -> date | datetime | None:
    try:
        return datetime.fromisoformat(text) if "T" in text else date.fromisoformat(text)
    except ValueError:
        return None


# --- loading ------------------------------------------------------------------

def load_declared(directory: Path, data_dir: Path, taken: set[str]) -> tuple[list[Provider], list[str]]:
    """Every declaration in a folder as a Provider. A broken one is skipped and reported, never fatal."""
    providers: list[Provider] = []
    errors: list[str] = []
    if not directory.is_dir():
        return providers, errors
    for path in sorted(directory.glob("*.json")):
        try:
            provider = declared_provider(json.loads(path.read_text(encoding="utf-8")), path.stem, data_dir)
            if provider.name in taken:
                raise ProviderError(f"{provider.name!r} is already a provider")
            taken.add(provider.name)
            providers.append(provider)
        except (ProviderError, OSError, ValueError, TypeError, KeyError) as err:
            errors.append(f"{path.name}: {err}")
    return providers, errors


def declared_provider(spec: dict[str, Any], stem: str, data_dir: Path) -> Provider:
    name = spec.get("name") or stem
    if name != stem:
        raise ProviderError(f"name {name!r} doesn't match the file name {stem!r}")
    description = _need(spec, "description", str)
    source = _need(spec, "source", dict)
    file = data_dir / _need(source, "file", str)
    list_ptr = "/" + _need(source, "list", str).strip("/")
    key = list_ptr.rsplit("/", 1)[-1]
    try:
        doc = json.loads(file.read_text(encoding="utf-8"))
    except FileNotFoundError as err:
        raise ProviderError(f"data file {file} not found") from err
    items = _at(doc, list_ptr)
    if not isinstance(items, list) or not all(isinstance(i, dict) for i in items):
        raise ProviderError(f"{file.name}{list_ptr} is not a list of objects")

    item_fields = {p[len("/*/"):] for p in pointer_patterns(items) if p.startswith("/*/")}

    def check_field(where: str, field: str) -> str:
        field = field.strip("/")
        if field not in item_fields:
            raise ProviderError(f"{where}: no field {field!r} in {file.name}{list_ptr} (fields: {', '.join(sorted(item_fields))})")
        return field

    sort = spec.get("sort")
    if sort is not None:
        check_field("sort.by", _need(sort, "by", str))
        if sort.get("order", "asc") not in ("asc", "desc"):
            raise ProviderError("sort.order must be asc or desc")

    params, filters = [], []
    for pname, p in (spec.get("params") or {}).items():
        ptype = p.get("type", "string")
        if ptype not in TYPES:
            raise ProviderError(f"param {pname!r}: type must be one of {TYPES}")
        f = _need(p, "filter", dict, f"param {pname!r}")
        op = f.get("op")
        if op == LIMIT:
            if ptype != "number":
                raise ProviderError(f"param {pname!r}: a limit is a number")
            field = None
        elif op in OPS:
            field = check_field(f"param {pname!r}", _need(f, "field", str, f"param {pname!r} filter"))
        else:
            raise ProviderError(f"param {pname!r}: op must be one of {[*OPS, LIMIT]}")
        switch = "value" in f
        if switch and ptype != "boolean":
            raise ProviderError(f"param {pname!r}: a filter with a fixed value is a switch, so its type is boolean")
        if ptype == "boolean" and not switch:
            raise ProviderError(f"param {pname!r}: a boolean param needs a fixed filter value (what it switches on)")
        choices = p.get("choices")
        if choices == "data":
            if field is None:
                raise ProviderError(f"param {pname!r}: choices from data need a filter field")
            choices = _distinct(v for i in items for v in values_at(i, field))
        elif choices is not None and not (isinstance(choices, list) and all(isinstance(c, str) for c in choices)):
            raise ProviderError(f"param {pname!r}: choices must be \"data\" or a list of strings")
        if choices is not None and ptype != "string":
            raise ProviderError(f"param {pname!r}: only string params have choices")
        params.append(Param(pname, ptype, _need(p, "description", str, f"param {pname!r}"),
                            required=bool(p.get("required")),
                            choices=(lambda c=tuple(choices): list(c)) if choices is not None else None))
        filters.append({"param": pname, "op": op, "field": field, "switch": switch, "value": f.get("value"),
                        "label": p.get("label")})

    computed = spec.get("computed") or {}
    for target, text in computed.items():
        if not isinstance(text, str):
            raise ProviderError(f"computed {target!r} must be a text template")
        rows = [o for i in items for o in _objects_at(i, target.rpartition("/")[0])]
        never = {m.group(1) for m in PLACEHOLDER.finditer(text)} - {k for row in rows for k in row}
        if never:  # most likely a typo; an item that merely lacks the field just gets ""
            raise ProviderError(f"computed {target!r} uses {sorted(never)}, which no item has")

    summary = spec.get("summary") or {}
    if summary and not all(isinstance(summary.get(k), str) for k in ("all", "filtered", "empty")):
        raise ProviderError('summary needs "all", "filtered" and "empty" sentences')

    def read(args: dict[str, Any]) -> dict[str, Any]:
        shown = copy.deepcopy(items)
        if sort:
            by, desc = sort["by"], sort.get("order") == "desc"
            present = [i for i in shown if values_at(i, by)]
            present.sort(key=lambda i: _sort_key(values_at(i, by)[0]), reverse=desc)
            shown = present + [i for i in shown if not values_at(i, by)]
        active: list[str] = []
        narrowed = False
        for f in filters:
            arg = args.get(f["param"])
            if arg is None or (f["switch"] and not arg):
                continue
            narrowed = True
            if f["op"] == LIMIT:
                shown = shown[: max(0, int(arg))]
            else:
                want = f["value"] if f["switch"] else arg
                shown = [i for i in shown if _passes(i, f["field"], f["op"], want)]
            if f["label"]:
                active.append(fill(f["label"], {"value": arg}))
        for target, text in computed.items():
            parent, _, leaf = target.rpartition("/")
            for item in shown:
                for obj in _objects_at(item, parent):
                    obj[leaf] = fill(text, obj)
        out: dict[str, Any] = {key: shown, "count": len(shown)}
        if summary:
            case = "empty" if not shown else "filtered" if narrowed else "all"
            text = fill(summary[case], {"count": len(shown), "total": len(items), "filters": " and ".join(active)})
            out["summary"] = re.sub(r"\s+([.,;:!?])", r"\1", text).strip()  # "orders ." when no filter has a label
        return out

    provider = Provider(name=name, description=description, params=params, fields=frozenset(), read=read,
                        origin=f"{file.parent.name}/{file.name}")
    cases = _cases(provider, filters, items)
    # The field schema is what the provider really returns (running every case also proves each param works).
    fields = set().union(*(pointer_patterns(provider.call(c)) for c in cases))
    return replace(provider, fields=frozenset(fields), cases=tuple(cases))


def _passes(item: dict[str, Any], field: str, op: str, want: Any) -> bool:
    test = OPS[op]
    have = values_at(item, field)
    if op == "ne":
        return all(test(v, want) for v in have)
    for v in have:
        try:
            if test(v, want):
                return True
        except (TypeError, ValueError):
            continue
    return False


def _sort_key(v: Any) -> tuple[int, Any]:
    return (0, float(v)) if isinstance(v, (int, float)) and not isinstance(v, bool) else (1, str(v))


def _cases(provider: Provider, filters: list[dict[str, Any]], items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Param sets that exercise every param with a value taken from the data ({} first):
    the tests run these, so a declaration is checked without anyone writing a test."""
    samples: dict[str, Any] = {}
    for f, p in zip(filters, provider.params, strict=True):
        if f["op"] == LIMIT:
            samples[p.name] = "2"
        elif f["switch"]:
            samples[p.name] = "true"
        elif p.choices:
            samples[p.name] = p.choices()[0]
        else:
            seen = sorted((v for i in items for v in values_at(i, f["field"]) if v is not None), key=_sort_key)
            if seen:
                samples[p.name] = str(seen[len(seen) // 2])
    base = {p.name: samples[p.name] for p in provider.params if p.required and p.name in samples}
    cases = [base, *({**base, name: v} for name, v in samples.items() if name not in base)]
    if len(samples) > 1:
        cases.append(dict(samples))
    return cases


def _distinct(values: Any) -> list[str]:
    out: list[str] = []
    for v in values:
        if v is not None and str(v) not in out:
            out.append(str(v))
    return out


def _at(doc: Any, pointer: str) -> Any:
    for key in [k for k in pointer.strip("/").split("/") if k]:
        if not isinstance(doc, dict) or key not in doc:
            raise ProviderError(f"no {pointer!r} in the data file")
        doc = doc[key]
    return doc


def _need(obj: dict[str, Any], key: str, kind: type, where: str = "") -> Any:
    v = obj.get(key) if isinstance(obj, dict) else None
    if not isinstance(v, kind) or v in ("", {}):
        prefix = f"{where}: " if where else ""
        raise ProviderError(f"{prefix}{key!r} is required ({kind.__name__})")
    return v
