"""FastAPI app: the AG-UI endpoint the React client's Chat tab talks to (reference: agui/server.js)."""

from __future__ import annotations

import asyncio
import warnings
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from .agui_bridge import CONTENT_TYPE, SSE_HEADERS, parse_run_input, stream_run
from .config import settings
from .data.providers import REGISTRY
from .generation.generate import generate_validated_a2ui, system_prompt
from .graph.playground import build_graph
from .ground.ground import Grounder
from .grounding.mcp import CatalogMcp
from .grounding.sources import Guidelines, LocalGuidelines, RagSource
from .grounding.catalog import generation_catalog, load_catalog
from .log import request_logger
from .state.checkpointer import open_checkpointer
from .templates.store import FileTemplateStore

PHASE = 8

# langchain-openai's strict structured output trips a harmless Pydantic serializer
# warning on every call (field `parsed`); keep the flow log readable.
warnings.filterwarnings("ignore", message="Pydantic serializer warnings", category=UserWarning)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Fail fast if the catalog is missing, and build the (large) system prompt once.
    catalog = load_catalog()
    prompt_chars = len(system_prompt())
    # Grounding (P7): the catalog MCP server (connected, or spawned from MCP_SERVER_SCRIPT) + guidelines.
    mcp = CatalogMcp()
    mcp_status = await mcp.start()
    guidelines = Guidelines()
    rag = next((s for s in guidelines.sources if isinstance(s, RagSource)), None)
    local = LocalGuidelines()
    # One shared graph; its checkpointer persists conversations keyed by thread_id.
    async with open_checkpointer(settings.database_url) as cp:
        app.state.graph = build_graph(cp.saver, grounder=Grounder(guidelines=guidelines, mcp=mcp))
        app.state.checkpointer_kind = cp.kind
        loop = asyncio.get_running_loop()
        durable = " — chat memory is NOT durable" if cp.kind == "memory" else ""
        print(f"AG-UI (Python, P{PHASE}) listening on http://localhost:{settings.port}", flush=True)
        print(f"  run endpoint:     POST http://localhost:{settings.port}/agui/run", flush=True)
        print(f"  generate UI tab:  POST http://localhost:{settings.port}/generate", flush=True)
        print(f"  event loop:       {type(loop).__name__}", flush=True)
        print(f"  checkpointer:     {cp.detail}{durable}", flush=True)
        print(f"  catalog:          {len(catalog['components'])} pds components ({catalog['catalogId']})", flush=True)
        manifests = FileTemplateStore(settings.templates_dir).manifests()
        print(f"  templates:        {', '.join(t.ref for t in manifests) or '(none)'} from {settings.templates_dir}", flush=True)
        declared = [p.name for p in REGISTRY.values() if p.origin != "code"]
        code = [p.name for p in REGISTRY.values() if p.origin == "code"]
        print(f"  data providers:   {', '.join(code)} (code); {', '.join(declared) or 'none'} declared in "
              f"{settings.providers_dir}{f' ({len(REGISTRY.errors)} skipped, see above)' if REGISTRY.errors else ''}", flush=True)
        print(f"  generator:        {settings.llm_provider} {settings.openai_model}, decide {settings.router_model}, "
              f"max repairs {settings.max_repairs}, prompt {prompt_chars:,} chars", flush=True)
        rules = local.all()
        kinds = {k: sum(1 for r in rules if r.kind == k) for k in ("hard", "soft", "pattern")}
        print(f"  guidelines:       {kinds['hard']} hard rules, {kinds['soft']} soft, {kinds['pattern']} patterns "
              f"from {settings.guidelines_dir}; judge {'on' if settings.guideline_judge else 'off'}", flush=True)
        rag_status = f"{rag.url} collection {rag.collection}" if rag and rag.enabled else "bypassed (RAG_URL not set)"
        print(f"  rag:              {rag_status}", flush=True)
        print(f"  mcp:              {mcp_status}", flush=True)
        try:
            yield
        finally:
            await mcp.stop()


app = FastAPI(title="A2UI GenUI playground backend", lifespan=lifespan)


@app.get("/agui/health")
async def health(request: Request) -> dict[str, Any]:
    return {
        "status": "ok",
        "phase": PHASE,
        "endpoint": "/agui/run",
        "checkpointer": request.app.state.checkpointer_kind,
    }


# --- "Generate UI" tab (decision D1: ported from src/index.js onto the gated generator) ---

@app.get("/health")
async def generate_health() -> dict[str, Any]:
    return {"status": "ok", "provider": settings.llm_provider, "catalogSource": "local"}


@app.post("/generate")
async def generate(request: Request) -> JSONResponse:
    """Body {prompt} -> {meta, a2ui}. Unlike Node's one-shot call, the result is gated and repaired."""
    log = request_logger("/generate")
    try:
        body = await request.json()
    except ValueError:
        body = None
    prompt = body.get("prompt") if isinstance(body, dict) else None
    if not isinstance(prompt, str) or not prompt:
        log.start("rejected — missing/invalid prompt")
        log.fail("400 Bad Request")
        return JSONResponse({"error": 'Request body must include a non-empty "prompt" string.'}, status_code=400)

    log.start(f'prompt "{prompt[:60]}" ({len(prompt)} chars)')
    generate_ui = getattr(request.app.state, "generate_ui", generate_validated_a2ui)
    try:
        result = await generate_ui(prompt, log=log)
    except Exception as err:  # noqa: BLE001 — surface any failure as a JSON error
        log.fail(f"500 — {err}")
        return JSONResponse({"error": str(err) or "Internal error"}, status_code=500)

    if not result["ok"]:
        log.fail(f"422 — no valid UI after {result['attempts']} attempt(s)")
        return JSONResponse(
            {
                "error": f"The generated UI didn't pass validation after {result['attempts']} attempt(s).",
                "hint": "\n".join(f"- {e}" for e in result["errors"]),
            },
            status_code=422,
        )

    doc = result["a2ui"]
    catalog = generation_catalog()
    count = len(next((m["updateComponents"]["components"] for m in doc["a2ui"] if "updateComponents" in m), []))
    log.done(f"200 — {count} components, {result['attempts']} attempt(s)")
    meta = {
        **result["meta"],
        "catalogId": catalog["catalogId"],
        "components": catalog["names"],
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
    }
    return JSONResponse({"meta": meta, **doc})


@app.post("/agui/run")
async def run(request: Request) -> StreamingResponse:
    log = request_logger("/agui/run")
    try:
        body = await request.json()
    except ValueError:
        body = {}
    req = parse_run_input(body)
    log.start(f'SSE run — thread={req.thread_id}, run={req.run_id}, user="{req.user_text[:60]}"')
    return StreamingResponse(
        stream_run(request.app.state.graph, req, request.is_disconnected, log),
        media_type=CONTENT_TYPE,
        headers=SSE_HEADERS,
    )
