"""TEMPLATE build: curated surface + provider data, through the same gate as generated UI."""

from __future__ import annotations

import copy
from typing import Any

from ..data.providers import get_provider
from ..generation.gate import validate_a2ui_document
from ..generation.graph_check import validate_and_repair_graph
from .store import Template, TemplateError


def _components(surface: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in surface.get("a2ui", []):
        out.extend(m.get("updateComponents", {}).get("components", []))
    return out


def _is_binding(v: Any) -> bool:
    return isinstance(v, dict) and isinstance(v.get("path"), str) and set(v) == {"path"}


def _is_template_children(v: Any) -> bool:
    return isinstance(v, dict) and isinstance(v.get("path"), str) and isinstance(v.get("componentId"), str)


def _resolve(base: str, path: str) -> str:
    return path if path.startswith("/") else f"{base}/{path}"


def binding_paths(surface: dict[str, Any]) -> list[tuple[str, str]]:
    """Every data binding in a surface as (component id, absolute pointer pattern).

    Walks from "root" tracking the data scope the renderer uses: a list template
    `{path, componentId}` renders its item component once per array element, so
    relative paths inside it resolve under `<list path>/*`.
    """
    return _walk(surface)[0]


def component_scopes(surface: dict[str, Any]) -> dict[str, str]:
    """The data scope each reachable component renders in: "" at the top level,
    "/plans/*" inside a list template over /plans (relative bindings resolve there)."""
    return _walk(surface)[1]


def _walk(surface: dict[str, Any]) -> tuple[list[tuple[str, str]], dict[str, str]]:
    by_id = {c["id"]: c for c in _components(surface) if isinstance(c.get("id"), str)}
    found: list[tuple[str, str]] = []
    scopes: dict[str, str] = {}
    seen: set[tuple[str, str]] = set()

    def scan(comp_id: str, value: Any, base: str) -> None:
        if _is_binding(value):
            found.append((comp_id, _resolve(base, value["path"])))
        elif isinstance(value, dict):
            for k, v in value.items():
                if k != "functionCall":  # renderer function args (e.g. setData) are write targets, not bindings
                    scan(comp_id, v, base)
        elif isinstance(value, list):
            for v in value:
                scan(comp_id, v, base)

    def visit(comp_id: str, base: str) -> None:
        if (comp_id, base) in seen or comp_id not in by_id:
            return
        seen.add((comp_id, base))
        scopes.setdefault(comp_id, base)
        comp = by_id[comp_id]
        for key, value in comp.items():
            if key in ("id", "component"):
                continue
            if key == "child" and isinstance(value, str):
                visit(value, base)
            elif key == "children" and _is_template_children(value):
                list_path = _resolve(base, value["path"])
                found.append((comp_id, list_path))
                visit(value["componentId"], f"{list_path}/*")
            elif key == "children" and isinstance(value, list):
                for v in value:
                    if isinstance(v, str):
                        visit(v, base)
            elif key == "children" and isinstance(value, str) and value in by_id:
                visit(value, base)
            else:
                scan(comp_id, value, base)

    visit("root", "")
    return found, scopes


def render_template(template: Template, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Fill a template with provider data and gate it. Returns {a2ui, data, schema_validation}."""
    manifest = template.manifest
    data = get_provider(manifest.provider).call(params or {})

    surface = copy.deepcopy(template.surface)
    messages = surface["a2ui"]
    create = next((i for i, m in enumerate(messages) if "createSurface" in m), None)
    if create is None:
        raise TemplateError(f"{manifest.ref}: surface.json has no createSurface message")
    surface_id = messages[create]["createSurface"]["surfaceId"]
    messages.insert(create + 1, {
        "version": "v0.9",
        "updateDataModel": {"surfaceId": surface_id, "path": "/", "value": data},
    })

    graph = validate_and_repair_graph(surface)
    schema = validate_a2ui_document(surface)
    problems = graph["errors"] + [f'{f["id"]} ({f["component"]}): {"; ".join(f["issues"])}' for f in schema["failures"]]
    if problems:
        raise TemplateError(f"{manifest.ref} failed the gate: {' | '.join(problems)}")
    return {"a2ui": surface, "data": data, "schema_validation": schema}
