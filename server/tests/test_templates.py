"""The curated template library: a broken template fails CI, not the demo."""

from __future__ import annotations

import json

import pytest

from app.config import settings
from app.data.providers import REGISTRY, ProviderError, field_matches, get_provider, pointer_patterns
from app.templates.render import binding_paths, render_template
from app.templates.store import FileTemplateStore

STORE = FileTemplateStore(settings.templates_dir)
MANIFESTS = STORE.manifests()
IDS = [m.id for m in MANIFESTS]

# Param sets each code provider is exercised with (defaults + every param). Declared
# providers (data/providers/*.json) derive theirs from their data (Provider.cases).
CODE_PROVIDER_CASES = {
    "plans.list": [{}, {"maxPrice": "60"}, {"unlimitedOnly": "true"}, {"maxPrice": "60", "unlimitedOnly": "true"}, {"maxPrice": "10"}],
    "addons.list": [{}, {"planId": "unlimited-plus"}, {"planId": "starter-5"}],
}
PROVIDER_CASES = {name: CODE_PROVIDER_CASES.get(name) or list(p.cases) for name, p in REGISTRY.items()}


def test_starter_templates_exist():
    assert {"plan-tiles", "plan-addons"} <= set(IDS)


def test_every_provider_has_test_cases():
    assert set(CODE_PROVIDER_CASES) <= set(REGISTRY)
    assert all(PROVIDER_CASES[name] for name in REGISTRY), "a provider with no param cases isn't tested"


def test_every_provider_declaration_loads():
    assert not REGISTRY.errors, f"broken provider declarations: {REGISTRY.errors}"


@pytest.mark.parametrize("template_id", IDS)
def test_manifest_provider_exists(template_id):
    manifest = STORE.get(template_id).manifest
    assert manifest.provider in REGISTRY
    assert manifest.personas and set(manifest.personas) <= {"assistant", "explorer"}


@pytest.mark.parametrize("template_id", IDS)
def test_every_binding_exists_in_the_provider_field_schema(template_id):
    template = STORE.get(template_id)
    fields = get_provider(template.manifest.provider).fields
    unknown = [(cid, p) for cid, p in binding_paths(template.surface) if not field_matches(fields, p)]
    assert not unknown, f"{template_id} binds to fields its provider doesn't declare: {unknown}"


@pytest.mark.parametrize("template_id", IDS)
def test_surface_has_no_data_and_uses_surface_main(template_id):
    messages = STORE.get(template_id).surface["a2ui"]
    assert not any("updateDataModel" in m for m in messages), "data comes from the provider, not the template"
    ids = {m[k]["surfaceId"] for m in messages for k in m if k != "version"}
    assert ids == {"main"}


@pytest.mark.parametrize("template_id", IDS)
def test_renders_through_the_gate_with_every_param_case(template_id):
    template = STORE.get(template_id)
    for params in PROVIDER_CASES[template.manifest.provider]:
        rendered = render_template(template, params)  # raises TemplateError if the gate fails
        kinds = [next(k for k in m if k != "version") for m in rendered["a2ui"]["a2ui"]]
        assert kinds == ["createSurface", "updateDataModel", "updateComponents"]


@pytest.mark.parametrize("template_id", IDS)
def test_rendering_is_deterministic(template_id):
    template = STORE.get(template_id)
    a = render_template(template, {})["a2ui"]
    b = render_template(template, {})["a2ui"]
    assert json.dumps(a) == json.dumps(b)


@pytest.mark.parametrize("name", sorted(REGISTRY))
def test_provider_output_stays_inside_its_field_schema(name):
    provider = get_provider(name)
    for params in PROVIDER_CASES[name]:
        extra = pointer_patterns(provider.call(params)) - provider.fields
        assert not extra, f"{name}{params} returned undeclared fields: {sorted(extra)}"


def test_plans_filtering():
    plans = get_provider("plans.list")
    got = plans.call({"maxPrice": "60", "unlimitedOnly": "true"})
    assert [p["id"] for p in got["plans"]] == ["unlimited-go"]
    assert got["summary"] == "1 of 5 plans with unlimited data and up to $60/mo."
    assert plans.call({"maxPrice": "$10"})["plans"] == []


def test_addons_for_a_plan_and_bad_param():
    addons = get_provider("addons.list")
    got = addons.call({"planId": "starter-5"})
    assert got["heading"] == "Add-ons for Starter 5"
    assert {a["id"] for a in got["addons"]} == {"intl-pass", "device-protect", "cloud-200"}
    with pytest.raises(ProviderError):
        addons.call({"planId": "no-such-plan"})


def test_binding_paths_resolve_list_scopes():
    paths = {p for _, p in binding_paths(STORE.get("plan-tiles").surface)}
    assert {"/summary", "/plans", "/plans/*/name", "/plans/*/features", "/plans/*/features/*/text", "/plans/*/id"} <= paths


def _events_in(surface: dict) -> set[str]:
    found = set()

    def walk(v):
        if isinstance(v, dict):
            if isinstance(v.get("event"), dict) and isinstance(v["event"].get("name"), str):
                found.add(v["event"]["name"])
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)

    walk(surface)
    return found


@pytest.mark.parametrize("template_id", IDS)
def test_every_event_a_template_emits_is_declared(template_id):
    template = STORE.get(template_id)
    assert _events_in(template.surface) == set(template.manifest.events)


@pytest.mark.parametrize("template_id", IDS)
def test_suggested_next_templates_exist(template_id):
    assert set(STORE.get(template_id).manifest.suggested_next) <= set(IDS)
