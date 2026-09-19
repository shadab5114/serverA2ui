"""Tolerant JSON parse and per-model-family params (ported from src/llm.js)."""

from __future__ import annotations

import pytest

from app.generation.llm import openai_params, parse_json


@pytest.mark.parametrize("text", [
    '{"a2ui": []}',
    'Here you go:\n```json\n{"a2ui": []}\n```',
    '```\n{"a2ui": []}\n```',
    'Sure! {"a2ui": []} Hope that helps.',
])
def test_parse_json_tolerates_wrapping(text):
    assert parse_json(text) == {"a2ui": []}


@pytest.mark.parametrize("text", ["", "no json here"])
def test_parse_json_rejects_garbage(text):
    with pytest.raises(ValueError):
        parse_json(text)


@pytest.mark.parametrize("model", ["gpt-5", "gpt-5-mini", "o1", "o3-mini", "O4-mini"])
def test_reasoning_models_get_completion_tokens_and_no_temperature(model):
    assert openai_params(model, 6000) == {"max_completion_tokens": 6000, "reasoning_effort": "low"}


@pytest.mark.parametrize("model", ["gpt-4o", "gpt-4o-mini", "gpt-4.1", "omni-x"])
def test_other_models_get_temperature_and_max_tokens(model):
    assert openai_params(model, 6000) == {"temperature": 0.2, "max_tokens": 6000}


async def test_an_unusable_reply_is_a_retried_attempt_not_a_crash():
    from app.generation.generate import generate_validated_a2ui
    from tests.test_contract import VALID_DOC

    replies = iter([ValueError("LLM returned empty content."), VALID_DOC])

    async def generate(system_prompt, user_prompt):
        r = next(replies)
        if isinstance(r, Exception):
            raise r
        return {"json": r, "provider": "fake", "model": "fake-1"}

    result = await generate_validated_a2ui("a form", generate=generate)
    assert result["ok"] and result["attempts"] == 2
