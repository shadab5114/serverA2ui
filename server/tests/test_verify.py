"""Hard rules (lints) and the local guideline library."""

from __future__ import annotations

import asyncio
import json

import httpx
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


def fake_rag(body, status=200, seen=None) -> RagSource:
    """A RagSource wired to a canned /query response (D2's contract), recording the request."""
    def handle(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append({"url": str(request.url), "json": json.loads(request.content)})
        return httpx.Response(status, json=body)

    return RagSource(url="http://127.0.0.1:5000/query", collection="design_system",
                     transport=httpx.MockTransport(handle))


def test_rag_sends_query_and_collection_name():
    seen = []
    res = asyncio.run(fake_rag({"answer": "Use one primary button.", "citations": []}, seen=seen).search("make it louder"))
    assert seen == [{"url": "http://127.0.0.1:5000/query",
                     "json": {"query": "make it louder", "collection_name": "design_system"}}]
    # The service's answer is citable in its own right, so the brief and the patch prompts see it.
    [answer] = res.sources
    assert (answer.id, answer.title, answer.text, answer.origin) == (
        "RAG-ANSWER", "Guidance for this request", "Use one primary button.", "rag/design_system")
    assert res.answer == "Use one primary button." and res.note == ""


def test_rag_citations_become_citable_sources():
    res = RagSource._parse({
        "answer": "One primary per screen.",
        "citations": [
            {"title": "DS-101 · Primary buttons", "text": "One primary.", "source": "rules/buttons.md", "page": 2},
            {"title": "Tiles", "snippet": "Keep tiles alike."},  # no ref: falls back to the collection
            "docs/spacing-scale.md",  # citations as bare document refs
        ],
    }, origin="rag/design_system")
    assert [(s.id, s.title, s.origin) for s in res.sources] == [
        ("RAG-ANSWER", "Guidance for this request", "rag/design_system"),
        ("DS-101", "DS-101 · Primary buttons p.2", "rules/buttons.md"),  # a cited rule keeps its id
        ("RAG-2", "Tiles", "rag/design_system"),
        ("RAG-3", "spacing scale", "docs/spacing-scale.md"),
    ]
    assert res.sources[1].kind == "hard" and res.sources[2].text == "Keep tiles alike."


def test_rag_reads_answers_as_a_list_too():
    # GENUI-PORTING-PLAN.md S5 describes the same service answering with "answers".
    res = RagSource._parse({"answers": ["One primary per screen.", "Label every field."]})
    assert res.sources[0].id == "RAG-ANSWER" and res.answer == "One primary per screen.\n\nLabel every field."


def test_rag_tolerates_an_empty_or_odd_response():
    assert RagSource._parse({}).sources == [] and RagSource._parse({}).note == "no answer and no citations"
    # Only citations, no answer, is still grounding; a single citation may come unwrapped.
    res = RagSource._parse({"citations": {"title": "Tiles", "text": "Alike."}})
    assert [(s.id, s.text) for s in res.sources] == [("RAG-1", "Alike.")]
    assert asyncio.run(fake_rag([1, 2]).search("x")).note.startswith("unexpected response: list")


def test_a_failing_rag_call_never_blocks_grounding():
    merged = asyncio.run(Guidelines([LOCAL, fake_rag({"detail": "no such collection"}, status=404)])
                         .search("sign-up form fields"))
    assert [s.origin for s in merged.sources] == ["guidelines/guidelines.md"] * len(merged.sources)
    assert "guidelines.rag: failed" in merged.note and "404" in merged.note


def test_local_rules_win_over_the_rag_copy_of_the_same_rule():
    rag = fake_rag({"answer": "", "citations": [{"title": "DS-101", "text": "stale copy"}]})
    merged = asyncio.run(Guidelines([LOCAL, rag]).search("DS-101 primary button"))
    [ds101] = [s for s in merged.sources if s.id == "DS-101"]
    assert ds101.origin == "guidelines/hard-rules.md" and "stale copy" not in ds101.text
