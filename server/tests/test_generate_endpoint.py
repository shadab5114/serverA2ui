"""POST /generate + GET /health, the "Generate UI" tab's API (decision D1)."""

from __future__ import annotations

import copy
import functools

import httpx
import pytest

from app.generation.generate import generate_validated_a2ui
from app.main import app
from tests.test_contract import VALID_DOC, invalid_doc


def use_docs(*docs):
    queue = [copy.deepcopy(d) for d in docs]

    async def generate(system_prompt: str, user_prompt: str):
        return {"json": queue.pop(0), "provider": "fake", "model": "fake-1"}

    app.state.generate_ui = functools.partial(generate_validated_a2ui, generate=generate)


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.state.generate_ui = generate_validated_a2ui


async def test_health(client):
    r = await client.get("/health")
    assert r.json() == {"status": "ok", "provider": "openai", "catalogSource": "local"}


@pytest.mark.parametrize("body", [{}, {"prompt": ""}, {"prompt": 5}])
async def test_bad_prompt_is_400(client, body):
    r = await client.post("/generate", json=body)
    assert r.status_code == 400
    assert r.json() == {"error": 'Request body must include a non-empty "prompt" string.'}


async def test_success_returns_meta_plus_a2ui(client):
    use_docs(invalid_doc(), VALID_DOC)
    r = await client.post("/generate", json={"prompt": "sign-up form"})
    assert r.status_code == 200
    data = r.json()
    assert list(data) == ["meta", "a2ui"]
    assert data["a2ui"] == VALID_DOC["a2ui"]
    meta = data["meta"]
    assert meta["attempts"] == 2 and meta["provider"] == "fake"
    assert "Column" in meta["components"] and "Button" in meta["components"]
    assert meta["catalogId"] and meta["generatedAt"].endswith("Z")


async def test_gate_failure_is_422_with_the_errors_as_hint(client):
    use_docs(invalid_doc(), invalid_doc(), invalid_doc())
    r = await client.post("/generate", json={"prompt": "sign-up form"})
    assert r.status_code == 422
    data = r.json()
    assert data["error"] == "The generated UI didn't pass validation after 3 attempt(s)."
    assert data["hint"].startswith('- Component "submit" (Button): kind: ')
