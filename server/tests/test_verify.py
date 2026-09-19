"""Hard rules (lints) and the local guideline library."""

from __future__ import annotations

import asyncio

import pytest

from app.config import settings
from app.grounding.sources import Guidelines, LocalGuidelines, RagSource
from app.templates.store import FileTemplateStore
from app.verify.lints import LINTS, lint_document, lint_messages

LOCAL = LocalGuidelines()
TEMPLATES = FileTemplateStore(settings.templates_dir)


def doc(*components) -> dict:
    return {"a2ui": [{"version": "v0.9", "updateComponents": {"surfaceId": "main", "components": [
        {"id": "root", "component": "Column", "children": [c["id"] for c in components]}, *components]}}]}


def rules_hit(d) -> list[str]:
    return sorted({v.rule_id for v in lint_document(d)})


def test_every_hard_rule_in_markdown_has_a_lint_and_back():
    documented = {s.id for s in LOCAL.all() if s.kind == "hard"}
    assert documented == set(LINTS)


def test_guideline_ids_are_unique():
    ids = [s.id for s in LOCAL.all()]
    assert len(ids) == len(set(ids)) and len(ids) >= 10


@pytest.mark.parametrize("template_id", [m.id for m in TEMPLATES.manifests()])
def test_curated_templates_pass_every_hard_rule(template_id):
    assert lint_messages(TEMPLATES.get(template_id).surface)[0] == []


def test_ds101_primary_buttons():
    assert rules_hit(doc({"id": "a", "component": "Button", "children": "Go"})) == []
    assert rules_hit(doc({"id": "a", "component": "Button", "children": "Go"},
                         {"id": "b", "component": "Button", "kind": "secondary", "children": "Back"})) == []
    assert rules_hit(doc({"id": "a", "component": "Button", "children": "Go"},
                         {"id": "b", "component": "Button", "children": "Also go"})) == ["DS-101"]


def test_ds101_primary_button_in_a_list_item():
    d = {"a2ui": [{"updateComponents": {"components": [
        {"id": "root", "component": "Column", "children": {"path": "/items", "componentId": "row"}},
        {"id": "row", "component": "Row", "children": ["buy"]},
        {"id": "buy", "component": "Button", "children": "Buy"},
    ]}}]}
    [v] = lint_document(d)
    assert v.rule_id == "DS-101" and v.component_ids == ("buy",) and "repeated" in v.detail


def test_ds102_to_ds105():
    assert rules_hit(doc({"id": "f", "component": "InputField"})) == ["DS-102"]
    assert rules_hit(doc({"id": "f", "component": "InputField", "label": "Email"})) == []
    assert rules_hit(doc({"id": "b", "component": "Badge", "children": "Our absolute best value ever"})) == ["DS-103"]
    assert rules_hit(doc({"id": "b", "component": "Badge", "children": {"path": "badge"}})) == []  # data, not a literal
    assert rules_hit(doc({"id": "i", "component": "Image", "src": "a.png"})) == ["DS-104"]
    assert rules_hit(doc({"id": "t", "component": "Text", "children": "Just $55/mo"})) == ["DS-105"]
    assert rules_hit(doc({"id": "t", "component": "Text", "children": {"path": "/plans/0/priceLabel"}})) == []


def test_lint_messages_quote_the_rule():
    [line], _ = lint_messages(doc({"id": "i", "component": "Image", "src": "a.png"}))
    assert line.startswith("Guideline [DS-104 · Images have alt text] (component i): image without alt text.")
    assert "Rule: Every `Image` has a non-empty `alt`" in line


def test_local_search_finds_patterns_by_intent():
    res = asyncio.run(LOCAL.search("which plan fits someone who travels, recommend one"))
    assert "PAT-301" in [s.id for s in res.sources]


def test_rag_is_bypassed_until_configured():
    res = asyncio.run(RagSource(url="").search("anything"))
    assert res.sources == [] and res.note.startswith("bypassed")
    merged = asyncio.run(Guidelines([LOCAL, RagSource(url="")]).search("sign-up form fields"))
    assert merged.sources and "guidelines.rag: bypassed" in merged.note


def test_rag_response_adapter():
    res = RagSource._parse({"answer": "Use one primary.", "sources": [
        {"id": "g-1", "title": "Buttons", "excerpt": "One primary.", "uri": "https://ds/buttons"}]})
    assert res.answer == "Use one primary."
    assert (res.sources[0].id, res.sources[0].text, res.sources[0].origin) == ("g-1", "One primary.", "https://ds/buttons")
