# Conversational App Backend — Architecture & Execution Plan

**Stack:** TypeScript (Bun) · LangGraph · A2UI · AG-UI · Fastify · Postgres · Redis
**Context:** Building inside the existing repo, which already contains a basic A2UI setup and `catalog.json`.

---

## 1. Core architectural principle

`catalog.json` is the single source of truth — but the LLM never consumes it raw at runtime.

A **build-time catalog compiler** derives three artifacts from it:

1. **Zod v4 schemas** for every component → runtime validation of generated A2UI
2. **Condensed component reference** → injected into the generator's system prompt
3. **TypeScript types** → compile-time safety across the repo

Consequence: LLM output is *proposed* A2UI. Nothing reaches the wire until the **validator gate** approves it against the catalog. Invalid output is repaired (bounded retry) or replaced with a plain-text fallback. This is what separates production generative UI from a demo.

```
catalog.json ──(build step)──▶ zod schemas + prompt reference + TS types
                                      │
user msg ─▶ AG-UI endpoint ─▶ LangGraph ─▶ validator gate ─▶ AG-UI events (SSE) ─▶ client renderer
                 ▲                                                                      │
                 └───────────────────── userAction events ◀─────────────────────────────┘
```

## 2. Request flow (one turn)

1. Client sends a message, or a `userAction` event from a rendered A2UI surface.
2. AG-UI endpoint receives `RunAgentInput`, opens an SSE stream, emits `RUN_STARTED`.
3. LangGraph graph executes:
   - **Router** — does this turn need UI at all, or just text?
   - **Planner** — which surface(s) to emit or update
   - **Generator** — produces A2UI JSONL, constrained by the compiled catalog reference
   - **Validator gate** — Zod check against generated schemas; on failure, repair loop (max 2 retries) with the Zod error fed back to the generator; final fallback = text message
4. Validated A2UI messages stream out as AG-UI UI events, interleaved with `TEXT_MESSAGE_CONTENT` deltas and `STATE_DELTA` events. `RUN_FINISHED` closes the turn.
5. User interacts with the rendered surface → `userAction` returns over AG-UI → the checkpointed graph resumes by `threadId` and updates or replaces the surface.

## 3. The stack, concretely

| Layer | Choice | Why |
|---|---|---|
| Runtime | Bun + TypeScript | Matches existing monorepo workspaces |
| HTTP | Fastify (or Hono) | Proper SSE backpressure; avoid Express for streaming |
| Agent | `@langchain/langgraph` + `@ag-ui/langgraph` | Lifecycle events (RUN_STARTED, deltas, tool events) emitted for free |
| UI spec | A2UI v0.9 | Declarative JSONL surfaces, client-rendered via native components |
| Transport | AG-UI over SSE | Event protocol; bidirectional via userAction round-trips |
| Validation | Zod v4 (generated from catalog) | Single source of truth; same pattern as the One App Strategy tool |
| Durable state | Postgres (LangGraph checkpointer) | Resume-by-threadId, time-travel debugging |
| Fast state | Redis | Sessions, rate limiting, hot cache of compiled catalog |
| Jobs | BullMQ | Anything slower than a turn; progress via STATE_DELTA |
| Observability | LangSmith (or Langfuse) + OpenTelemetry | "Why did it emit a Card there" is undebuggable without traces |

## 4. Robustness & scaling decisions

- **Stateless instances.** All conversation state lives in the Postgres checkpointer keyed by `threadId`. SSE reconnects can land on any instance → linear horizontal scaling behind a plain load balancer, no sticky sessions.
- **Repair loop, not just rejection.** Feeding Zod errors back to the generator (capped at 2 retries) typically lifts valid-output rate from ~85% to ~99%.
- **Eval harness in CI.** Prompt → expected-A2UI-shape test cases, so prompt or catalog changes can't silently regress UI quality.
- **Catalog contract tests.** `catalog.json` changes fail CI if they break compiled schemas or golden A2UI fixtures.
- **Never block the stream.** Slow tool calls go to BullMQ; the turn keeps streaming progress.

## 5. Repo layout (added to the existing repo)

```
apps/
  server/               # Fastify + AG-UI SSE endpoint
  web/                  # existing A2UI setup → becomes the AG-UI test client
packages/
  catalog-compiler/     # catalog.json → schemas + types + prompt reference
  a2ui-schemas/         # generated output (committed or built)
  agent/                # LangGraph graphs, nodes, prompts
  evals/                # prompt → A2UI-shape test suite
```

The existing A2UI setup stays where it is; it becomes the render target. New packages slot into the Bun workspace alongside it.

## 6. Phased execution plan (medium → advanced)

Each phase leaves something runnable and introduces exactly one new concept.

### Phase 0 — Audit & wire-up (existing repo)
- Inventory the current A2UI setup: renderer, catalog.json shape, any existing schemas.
- Add the new workspace packages (empty shells) to `package.json` workspaces.
- Decide what the existing client keeps vs. what moves behind the new server.
- **Done when:** repo builds with the new empty packages; a written note maps existing code → target layout.

### Phase 1 — Raw AG-UI endpoint (no LangGraph)
- Fastify server with an SSE endpoint that hand-emits AG-UI lifecycle events (`RUN_STARTED` → fake `TEXT_MESSAGE_*` deltas → `RUN_FINISHED`).
- Point the existing client at it.
- **Goal:** understand the event protocol at the byte level before a framework hides it.
- **Done when:** the client renders a streamed fake conversation end-to-end.

### Phase 2 — Catalog compiler
- Parse `catalog.json` → emit Zod schemas, TS types, prompt-ready component reference.
- Golden-fixture tests; wire into the build.
- Pure deterministic code — reuse patterns from the existing Zod-as-source-of-truth work.
- **Done when:** a hand-written A2UI payload validates (and a broken one fails) via generated schemas.

### Phase 3 — First graph
- Minimal LangGraph (router → responder), text-only, streamed via `@ag-ui/langgraph`.
- Add the Postgres checkpointer; prove resume-by-`threadId` across requests.
- **Done when:** a multi-turn text conversation survives a server restart.

### Phase 4 — Generative UI core ← go slowest here
- Add planner → A2UI generator → validator gate → repair loop.
- Stream validated A2UI as AG-UI UI events; render in the existing client.
- **Done when:** "show me a form for X" produces a catalog-valid surface, and a deliberately-broken prompt still degrades to text instead of crashing.

### Phase 5 — Bidirectional loop
- Handle `userAction` events: resume the checkpointed graph, mutate the surface or emit new ones.
- Add Redis: session affinity, rate limiting, compiled-catalog cache.
- **Done when:** clicking a button in a generated surface visibly updates that surface.

### Phase 6 — Production hardening
- LangSmith/OTel tracing end to end.
- Eval harness + catalog contract tests in CI.
- BullMQ for slow paths; load-test SSE fan-out; containerize; scale to 2+ instances behind a load balancer.
- **Done when:** a load test against 2 instances passes with reconnect-mid-stream working.

## 7. Key references

- A2UI spec & framework guide: https://a2ui.org
- AG-UI docs: https://docs.ag-ui.com
- LangGraph JS: https://langchain-ai.github.io/langgraphjs/
- `@ag-ui/langgraph` integration: published on npm; peer deps `@ag-ui/core`, `@ag-ui/client`
