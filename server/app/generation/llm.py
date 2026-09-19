"""One-shot A2UI generation call (reference: src/llm.js).

JSON mode, not strict structured outputs: OpenAI's strict mode can't express this
catalog (allOf, unevaluatedProperties), so output is validated by the gate and
repaired instead. The provider is chosen by LLM_PROVIDER (openai | anthropic).
Uses the raw SDKs, not LangChain, so these calls never surface as graph
chat-model events (nothing to filter in the bridge).
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, TypedDict

from ..config import settings

_REASONING_MODEL = re.compile(r"^(gpt-5|o\d)", re.IGNORECASE)
_FENCE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)

_openai_client = None


class Generation(TypedDict):
    json: Any
    provider: str
    model: str


def is_reasoning_model(model: str) -> bool:
    return bool(_REASONING_MODEL.match(model))


def openai_params(model: str, max_tokens: int) -> dict[str, Any]:
    """Reasoning models (gpt-5*, o<digit>*) take max_completion_tokens and no temperature.

    Their completion cap also has to hold their hidden reasoning, so they run at
    OPENAI_REASONING_EFFORT (default "low"): building JSON from a brief needs little
    deliberation, and higher effort both slows turns and can exhaust the cap.
    """
    if is_reasoning_model(model):
        effort = {"reasoning_effort": settings.reasoning_effort} if settings.reasoning_effort else {}
        return {"max_completion_tokens": max_tokens, **effort}
    return {"temperature": 0.2, "max_tokens": max_tokens}


def chat_model(model: str, temperature: float | None = None, **kwargs: Any):
    """A LangChain chat model for the small structured calls (decide, brief, judge),
    with the same per-family rules: reasoning models get reasoning_effort, no temperature."""
    from langchain_openai import ChatOpenAI

    if is_reasoning_model(model):
        extra = {"reasoning_effort": settings.reasoning_effort} if settings.reasoning_effort else {}
        return ChatOpenAI(model=model, **extra, **kwargs)
    return ChatOpenAI(model=model, **({"temperature": temperature} if temperature is not None else {}), **kwargs)


def parse_json(text: str) -> Any:
    """Parse model output as JSON, tolerating code fences or stray text around it."""
    if not text:
        raise ValueError("LLM returned empty content.")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    fenced = _FENCE.search(text)
    if fenced:
        try:
            return json.loads(fenced.group(1).strip())
        except json.JSONDecodeError:
            pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        return json.loads(text[start:end + 1])
    raise ValueError("LLM output was not valid JSON.")


async def generate_a2ui(system_prompt: str, user_prompt: str) -> Generation:
    if settings.llm_provider.lower() == "anthropic":
        return await _generate_with_anthropic(system_prompt, user_prompt)
    return await _generate_with_openai(system_prompt, user_prompt)


async def _generate_with_openai(system_prompt: str, user_prompt: str) -> Generation:
    global _openai_client
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is not set.")
    if _openai_client is None:
        from openai import AsyncOpenAI

        _openai_client = AsyncOpenAI()

    model = settings.openai_model
    # Capped so OpenAI doesn't reserve the model's full output window against the
    # per-minute token budget. 6k is ample for an A2UI document.
    completion = await _openai_client.chat.completions.create(
        model=model,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        **openai_params(model, settings.openai_max_tokens),
    )
    choice = completion.choices[0] if completion.choices else None
    content = (choice.message.content if choice else "") or ""
    if not content and choice is not None and choice.finish_reason == "length":
        raise ValueError(
            f"The model ran out of output tokens before writing any JSON (OPENAI_MAX_TOKENS={settings.openai_max_tokens}; "
            "reasoning models spend part of it thinking)."
        )
    return {"json": parse_json(content), "provider": "openai", "model": model}


async def _generate_with_anthropic(system_prompt: str, user_prompt: str) -> Generation:
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise RuntimeError("ANTHROPIC_API_KEY is not set.")
    try:
        from anthropic import AsyncAnthropic
    except ImportError as err:  # optional: only needed when LLM_PROVIDER=anthropic
        raise RuntimeError("LLM_PROVIDER=anthropic needs the SDK: `uv add anthropic` in server/.") from err

    model = settings.anthropic_model
    message = await AsyncAnthropic().messages.create(
        model=model,
        max_tokens=16000,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )
    text = "".join(b.text for b in message.content if b.type == "text").strip()
    return {"json": parse_json(text), "provider": "anthropic", "model": model}
