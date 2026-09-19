"""Validator gate: the 7 cases ported from test/catalogSchemas.test.mjs, plus the
cases that document the intended (stricter) catalog.json semantics."""

from __future__ import annotations

from app.generation.gate import known_components, validate_a2ui_document, validate_component


def surface(*components):
    return {
        "a2ui": [
            {"version": "v0.9", "createSurface": {"surfaceId": "main", "catalogId": "x"}},
            {"version": "v0.9", "updateComponents": {"surfaceId": "main", "components": list(components)}},
        ]
    }


# --- ported from test/catalogSchemas.test.mjs --------------------------------

def test_the_design_system_exposes_schemas_for_its_components():
    names = known_components()
    assert "Button" in names and "InputField" in names
    assert len(names) >= 30


def test_a_valid_hand_written_payload_passes():
    doc = surface(
        {"id": "root", "component": "Button", "children": "Sign in", "kind": "primary", "size": "large", "disabled": False},
        {"id": "email", "component": "InputField", "label": "Email", "value": {"path": "/form/email"}},
    )
    r = validate_a2ui_document(doc)
    assert r["valid"], r["failures"]
    assert r["checked"] == 2


def test_a_bad_enum_value_fails():
    r = validate_component({"id": "b", "component": "Button", "children": "x", "kind": "tertiary"})
    assert not r["ok"]
    assert any("kind" in i for i in r["issues"]), r["issues"]


def test_a_wrong_typed_prop_fails():
    r = validate_component({"id": "b", "component": "Button", "children": "x", "disabled": "yes"})
    assert not r["ok"]
    assert any("disabled" in i for i in r["issues"]), r["issues"]


def test_a_broken_payload_is_reported_as_invalid_with_failures():
    doc = surface(
        {"id": "root", "component": "Button", "children": "ok", "kind": "primary"},
        {"id": "bad", "component": "Button", "children": "x", "size": "gigantic"},
    )
    r = validate_a2ui_document(doc)
    assert not r["valid"]
    assert len(r["failures"]) == 1
    assert r["failures"][0]["id"] == "bad"


def test_unknown_non_pds_components_are_reported_not_failed():
    doc = surface(
        {"id": "root", "component": "Column", "children": ["a"]},  # borrowed layout, no pds schema
        {"id": "a", "component": "Button", "children": "hi"},
    )
    r = validate_a2ui_document(doc)
    assert r["valid"]
    assert "Column" in r["unknownComponents"]
    assert r["checked"] == 1  # only the Button was schema-checked


def test_action_is_accepted_because_the_catalog_declares_it():
    # Node tolerated `action` because Zod ignored unknown keys; here it's accepted
    # because $defs/CatalogComponentCommon declares it.
    r = validate_component(
        {"id": "b", "component": "Button", "children": "Submit", "action": {"event": {"name": "submit"}}}
    )
    assert r["ok"], r["issues"]


# --- intended strictness (new vs Node) ---------------------------------------

def test_an_undeclared_prop_is_rejected():
    r = validate_component({"id": "b", "component": "Button", "children": "x", "foo": 1})
    assert not r["ok"]
    assert any("foo" in i for i in r["issues"]), r["issues"]


def test_a_binding_on_a_dynamic_prop_is_accepted_natively():
    r = validate_component({"id": "f", "component": "InputField", "label": "Email", "value": {"path": "/x"}})
    assert r["ok"], r["issues"]


def test_checks_and_weight_validate():
    r = validate_component({
        "id": "b", "component": "Button", "children": "Go", "weight": 1,
        "checks": [{"condition": {"path": "/form/ok"}, "message": "Fill the form"}],
        "action": {"functionCall": {"call": "setData", "args": {"path": "/ui/open", "value": True}}},
    })
    assert r["ok"], r["issues"]


def test_missing_component_name():
    r = validate_component({"id": "x"})
    assert r == {"ok": False, "component": "undefined", "id": "x", "unknown": False, "issues": ["missing 'component' name"]}


def test_issues_name_the_offending_path():
    r = validate_component({"id": "b", "component": "Button", "children": "x", "size": "gigantic"})
    assert r["issues"] and all(i.startswith("size: ") for i in r["issues"]), r["issues"]
