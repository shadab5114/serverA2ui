"""GROUND's retrieval questions: the context they're written from, and every way they degrade."""

from __future__ import annotations

import asyncio
from dataclasses import replace

from langchain_core.messages import AIMessage, HumanMessage

from app.config import settings
from app.ground import ground
from app.ground.ground import Grounder, _merge_results
from app.ground.questions import VOCABULARY, Ask, RetrievalQuestions, screen_components
from app.graph.state import recent_turns
from app.graph.trace import Tracer
from app.grounding.sources import GroundingResult, Guidelines, LocalGuidelines, Source
from app.templates.render import render_template
from app.templates.store import FileTemplateStore

OFF = Tracer.off()
STORE = FileTemplateStore(settings.templates_dir)
VAGUE = Ask(request="change the color of the badge to yellow", intent="recolour the tile badge",
            doing="changing Baseline · plan-tiles@1", history=["user: show me the data plans"],
            screen={"ComposableTileContainer": ["cap", "header"]})


def asks(*questions, need="what the design system allows"):
    async def ask(system, inputs):
        return RetrievalQuestions(need=need, questions=list(questions))
    return ask


def grounder(questions, sources=None) -> Grounder:
    return Grounder(guidelines=Guidelines(sources or [LocalGuidelines()]), mcp=None, questions=questions)


def test_the_screens_components_carry_the_design_systems_vocabulary():
    doc = render_template(STORE.get("plan-tiles"), {})["a2ui"]
    on_screen = screen_components(doc)
    # What the user calls "the badge" is a tile cap here: the question can only name it from this.
    assert "cap" in on_screen["ComposableTileContainer"] and "header" in on_screen["ComposableTileContainer"]
    assert "kind" in on_screen["Button"] and "component" not in on_screen["Text"]
    assert all(props == sorted(props) for props in on_screen.values())


def test_recent_turns_leaves_out_the_request_itself():
    state = {"messages": [HumanMessage("show me the data plans"), AIMessage("Here are the plans."),
                          HumanMessage("change the color of the badge to yellow")]}
    assert recent_turns(state) == ["user: show me the data plans", "assistant: Here are the plans."]
    assert recent_turns({"messages": [HumanMessage("first turn")]}) == []


def test_the_question_call_gets_the_message_the_screen_and_the_history():
    inputs = VAGUE.as_inputs()
    assert inputs["userMessage"] == "change the color of the badge to yellow"
    assert inputs["whatTheUserWants"] == "recolour the tile badge"
    assert inputs["componentsOnTheScreen"] == {"ComposableTileContainer": ["cap", "header"]}
    assert inputs["conversationSoFar"] == ["user: show me the data plans"]
    assert "notCoveredByTheCuratedScreens" not in inputs  # empties are left out
    # The catalog names travel with every ask: the questions must name real components, and a new
    # screen has nothing on screen to go by.
    assert "ComposableTileContainer" in inputs[VOCABULARY] and "InputField" in inputs[VOCABULARY]
    assert set(Ask(request="just this").as_inputs()) == {"userMessage", VOCABULARY}


def test_questions_replace_the_request_as_the_query():
    q = ["Which values does ComposableTileContainer.cap.backgroundColor accept?", "When is a yellow badge allowed?"]
    queries, notes = asyncio.run(grounder(asks(*q)).ask(VAGUE, OFF))
    assert queries == q and notes == []


def test_at_most_three_questions_are_asked():
    queries, _ = asyncio.run(grounder(asks("q1", "q2", "q3", "q4", "q5")).ask(VAGUE, OFF))
    assert queries == ["q1", "q2", "q3"]


def test_every_failure_falls_back_to_the_request_itself():
    async def broken(system, inputs):
        raise RuntimeError("model down")

    fallback = ["recolour the tile badge. change the color of the badge to yellow"]
    queries, notes = asyncio.run(grounder(broken).ask(VAGUE, OFF))
    assert queries == fallback and "failed" in notes[0]
    queries, notes = asyncio.run(grounder(asks()).ask(VAGUE, OFF))  # no questions came back
    assert queries == fallback and "empty" in notes[0]
    queries, notes = asyncio.run(grounder(asks("  ")).ask(VAGUE, OFF))  # only blanks
    assert queries == fallback and "empty" in notes[0]
    assert Ask(request="no intent known").fallback() == ["no intent known"]


def test_the_step_can_be_turned_off(monkeypatch):
    # Settings is frozen: swap in a copy with the switch off, where ground.py reads it.
    monkeypatch.setattr(ground, "settings", replace(settings, ground_questions=False))

    async def never(system, inputs):
        raise AssertionError("the questions model must not be called when the step is off")

    queries, notes = asyncio.run(grounder(never).ask(VAGUE, OFF))
    assert queries == VAGUE.fallback() and "GROUND_QUESTIONS" in notes[0]


def test_each_questions_hits_are_merged_in_question_order_and_bounded():
    def res(*ids):
        return GroundingResult("a", [Source(i, i, "t", "rag") for i in ids], "")

    merged = _merge_results([res("DS-201", "DS-202"), res("DS-202", "DS-203")])
    assert [s.id for s in merged.sources] == ["DS-201", "DS-202", "DS-203"]  # deduped, first question first
    assert merged.answer == "a\n\na"
    assert [s.id for s in _merge_results([res("A", "B"), res("C")], most=2).sources] == ["A", "B"]
    notes = _merge_results([res("A"), GroundingResult("", [], "rag failed"), GroundingResult("", [], "rag failed")]).note
    assert notes == "rag failed"  # the same note from two searches is said once


def test_one_question_keeps_the_single_result_as_it_is():
    only = GroundingResult("a", [Source("DS-201", "t", "t", "rag")], "note")
    assert _merge_results([only]) is only
