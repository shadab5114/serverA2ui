# Phase 0 — Audit & Wire-up (flat-layout adaptation)

This repo follows the plan in [`A2UI-BACKEND-ARCHITECTURE.md`](../A2UI-BACKEND-ARCHITECTURE.md)
but **keeps the current flat layout** instead of migrating to Bun/monorepo
workspaces. New code is added alongside the existing `src/`, not under
`apps/`/`packages/`. This note maps the doc's target layout onto what we
actually have and will build.

## Current inventory

| Area | Location | What it is |
|---|---|---|
| Existing LLM server | [`src/index.js`](../src/index.js) | Express `/generate`: fetch MCP catalog → build prompt → OpenAI → validate/repair → return A2UI JSON |
| MCP catalog client | [`src/mcpClient.js`](../src/mcpClient.js) | Fetches the component catalog live per request |
| System prompt | [`src/systemPrompt.js`](../src/systemPrompt.js) | Embeds catalog into the generator prompt |
| LLM adapter | [`src/llm.js`](../src/llm.js) | Pluggable OpenAI/Anthropic call |
| Graph validation | [`src/validateGraph.js`](../src/validateGraph.js) | Orphan/child sanity checks + repair |
| Layout fallback | [`src/basicLayoutCatalog.js`](../src/basicLayoutCatalog.js) | Borrowed Column/Row/List/Divider containers |
| Component catalog | [`outsource/catalog.json`](../outsource/catalog.json) | 78 KB — single source of truth |
| Render client | [`client/`](../client/) | Vite + React A2UI renderer (PDS components) |

## Doc target layout → this repo (flat)

| Doc package | Purpose | Where it lives here |
|---|---|---|
| `apps/server` | Fastify + AG-UI SSE endpoint | **`agui/`** (new, Phase 1) |
| `apps/web` | AG-UI test client | `client/` (existing) + `agui/test-client.html` (Phase 1 minimal client) |
| `packages/catalog-compiler` | catalog.json → schemas + types + prompt ref | *deferred* → Phase 2 (planned `catalog-compiler/`) |
| `packages/a2ui-schemas` | generated Zod/TS output | *deferred* → Phase 2 (planned `a2ui-schemas/`) |
| `packages/agent` | LangGraph graphs/nodes/prompts | *deferred* → Phase 3+; existing `src/` prompt/llm code folds in here |
| `packages/evals` | prompt → A2UI-shape suite | *deferred* → Phase 6 |

## Existing client: keep vs. move

- **Keep** the `client/` React A2UI renderer — it stays the render target for
  generated surfaces (Phase 4/5 wires it to AG-UI **UI** events).
- For **Phase 1** the "client" is a minimal standalone page
  ([`agui/test-client.html`](../agui/test-client.html)) that consumes the SSE
  stream and renders the fake text conversation. This isolates the event
  protocol before touching the React app.

## Infrastructure

Postgres (Phase 3 checkpointer), Redis (Phase 5), and BullMQ (Phase 6) are
**deferred until their phase**. Early phases stay zero-dependency (no
docker-compose yet).

## Build / runnable status

- Runtime stays **Node + npm** (existing `package.json`), not Bun.
- No compile step for the server code (plain ESM). `npm install` succeeds;
  `client/` builds via Vite as before.
- **Phase 0 done when:** repo installs and this mapping note exists. ✅
