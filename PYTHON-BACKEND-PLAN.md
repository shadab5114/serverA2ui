# Python Backend: Implementation Plan

Rebuild the GenUI playground backend in Python, inside this repo, **without the React client noticing**.
The client in `client/` keeps working as it does today. Everything under `server/` is new.

> **Starting a fresh session?** Read this whole file first, then check **Status** below and continue at the first unchecked phase.
> Work one phase at a time. A phase is done only when its **Done when** is observable in the React client (see *How we verify*).
> When a phase completes, tick it in **Status** and add a line to **Phase log** at the bottom.
>
> **Where things stand (2026-09-19):** P0–P8 are done and verified in the client. The Node backend is gone, so read "Node reference" mentions below as history. **User priorities (2026-09-19): this is a general tool; plans are only the test case. Generality first, then accuracy, then performance.** Keep domain examples out of prompts and engine code, and prove changes on the non-plan modify eval (`cd server && uv run pytest -m eval tests/test_modify_eval.py -s`, 11 cases, currently 11/11). Decision evals: 23 rows, 23/23 twice. **F5 is done (2026-09-19, verified in the client): providers can be declared as data, and `order-history` is a non-plan use case added without Python** (see F5). Open follow-ups: **F4** (faster guideline judge, eval first), plus F2 and F3. The work on branch `langraph-server` is **not committed yet**; ask the user before committing. Run everything with `npm run agui` (backend, which spawns the catalog MCP server) and `cd client && npm run dev`, and test with `npm test` (plus `cd server && uv run pytest -m eval` for all real-model evals). The Phase log at the bottom says what each phase built and any deliberate differences.

---

## Status

- [x] **P0** Scaffold `server/`, stub stream through the real client
- [x] **P1** Text branch: LangGraph + streaming + Postgres memory
- [x] **P2** Catalog, prompt, validator gate (test-verified parity)
- [x] **P3** UI branch: router + generator + repair loop → rendered surfaces
- [x] **P4** Parity sign-off, retire the Node backend
- [x] **P5** Static generative UI: shared curated template library + data providers
- [x] **P6** `userAction` round-trip + multi-step flows (plans → add-ons)
- [x] **P7** Grounding tools: MCP + RAG, visible tool calls
- [x] **P8** Explorer: template-seeded variants + patch refinement

P0–P4 are a **port**: same behavior, new language. P5–P8 are **new features** and are only outlined here. Refine each one when you reach it.

---

## Context in one paragraph

This is a *playground*, not a product. It shows how a design system (`@shadab5114/pds-core`) grounds an agent that generates UI. The agent emits A2UI v0.9 JSON, which travels over AG-UI (SSE) and is rendered by React with real PDS components. A Node backend (`agui/`, `agent/`, `src/`) already implements phases 0–4 of `A2UI-BACKEND-ARCHITECTURE.md`: text chat, LangGraph routing, validator-gated UI generation with repair, and Postgres memory. We are moving that backend to Python because LangGraph, AG-UI, MCP and RAG tooling are strongest there. The Node code stays untouched as the **reference implementation** until P4 deletes it.

Visual references, all in `docs/` (regenerate with `npm run docs:genui`):
- `docs/genui-stack.html`: every runtime entity and how they connect (the target of this plan)
- `docs/genui-playground-architecture.html`: layers, "one catalog, three jobs", how the backend decides, the two persona flows

---

## Decisions already made (don't reopen these)

| Topic | Decision | Why |
|---|---|---|
| Language / runtime | **Python 3.12** (installed: 3.12.3), managed with **uv** (installed: 0.7.18) | LangGraph and the grounding ecosystem are Python-first; `adispatch_custom_event` needs ≥3.11 |
| HTTP | **FastAPI + uvicorn**, SSE via `StreamingResponse` | Direct equivalent of the Fastify server |
| Agent | **`langgraph`**, `langchain-openai` | Same graph shape as `agent/graph.js` |
| AG-UI | **`ag-ui-protocol`** (`ag_ui.core`, `ag_ui.encoder`) | Official Python SDK, same event types |
| Validator gate | **`jsonschema` (Draft 2020-12) against `catalog.json`** | Python can't import the Zod schemas. See *Gotchas* 1–3 for what changes |
| LLM output mode | **JSON mode** (`response_format: json_object`) + gate + repair | OpenAI strict structured outputs can't express this catalog (`allOf`, `unevaluatedProperties` aren't supported), so keep generate→validate→repair |
| Memory | **`langgraph-checkpoint-postgres`** (async) in a **separate database `a2ui_py`** | JS and Python checkpoints use the same table names but incompatible formats |
| Wire contract | **Identical** to the Node server, same port **:8090** | The client is the parity test |
| Order | **Port to parity first, no new features until P4** | If port and features change together, a bug can't be pinned to either |
| Redis, BullMQ | **Out of scope** | Nothing in a playground needs them. Add only if sessions or rate limits start to matter |
| LangSmith | Optional, env-var only (`LANGSMITH_TRACING=true`) | Dev-time tracing, zero code |

## Open decisions (ask the user when you reach them)

- ✅ **D1, resolved 2026-09-19: ported into FastAPI** on the gated generator (`/generate` → `{meta, a2ui}`, 422 + validator errors as `hint` when it never passes), Vite proxy default → :8090. Original question: **what happens to `/generate`?** The client's "Generate UI" tab (`client/src/App.tsx`) calls `POST /generate`, proxied to Node Express on :8080. Deleting Node breaks that tab.
  *Recommended:* port it into the same FastAPI app. It's a thin wrapper over the P3 generator. Then change the one-line Vite proxy default for `/generate` and `/health` from `:8080` to `:8090` (config, not app code).
  *Alternative:* remove the tab from the client.
- ✅ **D2, resolved 2026-09-25: the RAG contract is `POST {query, collection_name}` → `{answer, citations}`**, served by the user's service at `http://127.0.0.1:5000/query` (`RAG_URL`, collection `RAG_COLLECTION`, default `design_system`; `RAG_TIMEOUT` 30 s). Implemented in `RagSource` (`app/grounding/sources.py`): the service's `answer` becomes a citable source of its own (id `RAG-ANSWER`, title "Guidance for this request" — the names `GENUI-PORTING-PLAN.md` S5 uses, so the office port doesn't rename anything) next to the `citations` it was built from, so it reaches the design brief, the ADAPT/REFINE prompts, the variant cards and the trace panel through the same `sources` list as the local markdown — no second prompt path. Citation shapes vary between servers, so `_citation` reads the usual key names (`text`/`snippet`/…, `source`/`uri`/…, `title`/…), tolerates bare strings, and ids them `RAG-<n>` unless the citation names a rule (`DS-101`), which merges it with the local copy (local text wins — `Guidelines` queries local first). RAG answers are **not** judged as soft rules here (`Source.kind` is `other`): prose isn't a checkable rule, and the local markdown still supplies the soft rules. (`GENUI-PORTING-PLAN.md` S5 makes the answer `kind: "soft"` — correct *there*, because that port deletes `LocalGuidelines` and RAG is the only source; it needs S5's explicit `kind` field, so do it with that refactor, not before.) The wire names in S5 were placeholders: the real ones are `query` (not `prompt`) and `answer` (not `answers`), and `_answer_text` accepts `answers` (string or list) too, so one adapter fits both. Unset `RAG_URL` still bypasses the call, and a failing call is a note on `guidelines.search`, never a broken turn. Queried on every grounded turn: GENERATE, and equally **ADAPT/REFINE**, where the query is `<DECIDE's intent>. <the user's words>` — which is why `Plan.as_meta()` now carries `intent` (it was dropped before, so `GROUND` never saw it).
- ✅ **D3 (2026-09-19): the catalog MCP server** `D:/DesignSystem/pds/mcp/catalog-server.mjs` (Streamable HTTP, tools `list_component_catalog`, `get_component_schema`, `resolve_intent_to_schema`). The backend connects at `MCP_URL`, or spawns it from `MCP_SERVER_SCRIPT` with `PDS_CATALOG_PATH` = the gate's catalog. No guideline MCP server yet. Original question: **guideline MCP servers.** URLs, transport (streamable HTTP vs stdio), and tool names. (Known already: a catalog MCP at `http://localhost:3939/mcp` with tools `list_component_catalog` and `get_component_schema`. Its URL is `MCP_URL` in `.env`.)
- **D4, when templates outgrow the repo: which object store?** P5 starts with JSON files in `templates/`, behind a `TemplateStore` interface, so an object store later is a swap, not a rewrite. Ask which store and when; don't build it speculatively.
- ⏸ **D5 (2026-09-19): placeholder rules** in `guidelines/hard-rules.md` (DS-101 one primary action, DS-102 labelled inputs, DS-103 short badges, DS-104 image alt text, DS-105 prices come from data), each with a lint in `app/verify/lints.py`; soft guidance and patterns in `guidelines/guidelines.md`. The design-system team should replace them. Original question: **which guidelines are hard rules?** Hard rules become deterministic lints (e.g. "at most one primary button per surface", if that's a real rule). Soft rules are judged against retrieved guidance. The design-system team owns this list; ask for it, don't invent rules.
- ✅ **P8 choices (2026-09-19, asked when P8 started):** explorer guideline conflicts are **flagged on the variant's card**, not paused with `interrupt()` (`personas.json` `onGuidelineConflict: "flag"`; hard rules and schema errors are still repaired); a REFINE renders as a **new card in the new turn** ("Variant 2 · rev 2"), not an in-place update, so no `a2ui_patch` event exists; **"promote variant" is deferred** (follow-up F3).
- **D6, after P4 (optional): protocol alignment.** Both of these were checked against the installed `@ag-ui/core`: it has `ACTIVITY_SNAPSHOT { messageId, activityType, content, replace }` / `ACTIVITY_DELTA { messageId, activityType, patch }` and `STEP_STARTED` / `STEP_FINISHED { stepName }`. Moving surfaces from `CUSTOM a2ui` to `ACTIVITY_SNAPSHOT`, refinements from `CUSTOM a2ui_patch` to `ACTIVITY_DELTA`, and the `status` event to `STEP_*` would leave `CUSTOM` unused, so other AG-UI clients could understand everything. It's a wire-contract change that needs a client update, so never do it during P0–P4. Ask before starting it.

## Follow-ups requested by the user (not scheduled yet)

- **F1 (2026-09-19): progress feedback while UI generates.** ✅ *Step 1 done 2026-09-19 (server-only stage + elapsed-seconds status, `app/graph/progress.py`); the richer options below are still open.* A UI turn takes ~20–35 s (router ~2 s, each generator attempt ~10–18 s), and the user wants to see what's happening so they keep waiting. Notes for when it's picked up:
  - *Chat tab, server-only:* the client already shows the latest `CUSTOM status` text in the pending bubble (`Chat.tsx`), so emitting more `status` events needs no client or wire change: "Choosing a layout…", "Generating UI…", "Checking against the design system…", "Fixing 2 issues (attempt 2/3)…". Dispatch them from `generate_validated_a2ui` via `adispatch_custom_event`. Smallest useful step.
  - *Richer:* a step list or elapsed timer in the bubble (client change), or AG-UI `STEP_STARTED`/`STEP_FINISHED` (that's **D6**, and P7's trace panel wants the same thing, so consider doing them together).
  - *Generate UI tab:* it's a plain `fetch`, so it can only show a spinner unless `/generate` streams (client change).
  - *Cutting the wait itself:* set `ROUTER_MODEL=gpt-4o-mini` in `server/.env` (the router currently falls back to `gpt-5-mini`, ~2 s). The generator model is the main cost. The ~147K-char system prompt is static, so OpenAI's automatic prompt caching should already apply to it.

- **F2 (2026-09-19): grounded GENERATE is slow and its layouts drift.** "I travel a lot, which plan fits?" takes ~80–110 s (generate_a2ui ~45 s per attempt on `gpt-5-mini`, judge ~20 s, brief ~8 s) and often needs a second attempt. The user accepted it for now ("look at it later"). Diagnosis from the client run:
  - The brief (PAT-301) asks for tiles that contain name, price, facts and a Choose button. The first attempt nested that body in `Tilelet`s, but `Tilelet` has no `children` prop, so the gate rejected it (`'children' was unexpected`). The repair then satisfied the gate by moving each plan's details **out of the tiles** into the root Column: a row of bare tiles followed by a loose stack of prices, facts and full-width buttons (duplicated facts too).
  - The judge passed it: soft rules like DS-203 ("every tile shows the same fields… then its action") didn't catch the broken structure.
  - P8's patch approach is itself a data point here: patching a curated screen with a prompt carrying only the needed schemas (~38K chars) returns 3 verified variants in ~17 s.
  - Ideas: make PAT-301 name `ComposableTileContainer` with a `children` body (the structure `plan-tiles` already proves), or give the generator the curated `plan-tiles` surface as a worked example; have the brief's component list drop components that can't hold the required content (check `children` in the catalog); a structural lint "an option's action and facts live inside its tile"; for speed, `ROUTER_MODEL=gpt-4o-mini`, a faster generator model, or `GUIDELINE_JUDGE=off`; trim the 147K-char system prompt to the brief's components (MCP `get_component_schema`) instead of the whole catalog.

- **F3 (2026-09-19, deferred from P8): promote a variant, and explorer GENERATE ×3.** "Promote" would write a variant (template + chain applied) as a new template version candidate in `templates/` for design review, never auto-published. Explorer GENERATE still builds one surface; ×3 means three parallel grounded generations, which is slow and costly (see F2).

- **F4 (2026-09-19): the guideline judge is now the slowest step of a modify turn.** "Make the Best value cap red": decide 3.7 s, modify 4.9 s, judge ~10 s, total 18.8 s; a button rename is ~13 s, of which the judge is 5.8 s. The judge runs on `ROUTER_MODEL` (gpt-5-mini) with the whole surface as input (`app/verify/judge.py`; called from `app/explore/modify.py` and `app/generation/generate.py`), and a background judge of the base screen runs in parallel so findings the screen already had are dropped. **Accuracy first:** there is no judge eval yet. Build one (real screens plus changes that do and don't break DS-2xx rules, checked in code), then try levers and keep only what holds accuracy: a faster model for the judge only, a smaller input (the changed components with their parents plus the change list), `reasoning_effort=minimal`, or skipping the judge when the change touches no soft rule's subject. Measure with the timing approach used in P8 (TOOL_CALL_START/RESULT timestamps from a real graph run).

- **F5 (2026-09-19): adding a use case still needs Python.** A new domain needs a template (content, fine) and a data provider in `server/app/data/providers.py` (code: params, filtering, computed labels, a declared field list). Goal: a provider described as data, e.g. `data/providers/<name>.json` naming the data file, the list, typed params and how each filters, with the field schema derived from the data (`pointer_patterns`). The registry loads code providers and declared ones side by side. Then prove it by adding a **non-plan use case end to end without touching Python** (data, provider declaration, template, and a DECIDE eval row), verified in the client. Keep the existing tests green (`test_templates.py` enforces bindings ⊂ provider fields).
  ✅ **As built (2026-09-19; verified in the client):**
  - **Declared providers** (`server/app/data/declared.py`, format in its docstring): `data/providers/<name>.json` names a data file and the list in it (a JSON pointer), an optional sort, typed params (`string`/`number`/`boolean`, required or not) each with a filter (`eq`, `ne`, `lt`, `lte`, `gt`, `gte`, `contains`, `limit`; a fixed `value` makes a boolean param an on/off switch; a field like `items/*/name` matches any element), `choices` (`"data"` = the field's values, shown to DECIDE and enforced), computed display fields (`{field:spec}`: Python number formats, `date` or strftime for ISO dates; nested targets like `items/*/label`) and `all`/`filtered`/`empty` summary sentences built from each active filter's `label`. Output: `{<list>: [...], count, summary}`. **The field schema is derived** by running the provider on every derived param case and taking `pointer_patterns` of the results, so it is what the provider really returns.
  - **Checked at load**, with the error naming the file: filter and sort fields must exist in the data, computed placeholders must exist on some item, op and type must fit (switch ⇔ boolean, choices only on strings), the name must match the file and must not shadow a code provider. A broken declaration is **skipped and reported, never fatal**: printed at startup (new `data providers:` line) and failed by `test_every_provider_declaration_loads`.
  - **One registry**: `REGISTRY` is now a live `Mapping` (`ProviderRegistry`) of code providers plus declared ones, re-read when a declaration or data file changes (like templates), so no call site changed. `PROVIDERS_DIR` (default `DATA_DIR/providers`).
  - **Tests need no Python per use case**: each declared provider derives `cases` (every param with a value taken from its data, then all together) and `test_templates.py` runs them through the gate, the binding check and the field check. `tests/test_declared_providers.py` covers the engine on a neutral fixture domain. Two small generic changes: a string choice matches case-insensitively and returns the canonical spelling ("delivered" → "Delivered"), and numbers accept thousands separators.
  - **The use case, content only**: `data/orders.json` (7 illustrative orders), `data/providers/orders.list.json` (status, minTotal, maxTotal, item, placedSince, limit; newest first; `totalLabel`, `placedLabel`, `items/*/label`), `templates/order-history/` (tiles with a status cap, total, date and the items). 6 new DECIDE rows (plain, status, min total, item, limit, explorer). New eval check `expect.shows` ({list: [ids]}) compares what the provider returns for the decided params, not the exact param text ("headphone" and "headphones" both find the order).
  - **Accuracy regression found and fixed:** adding a second domain's template made "I travel a lot, which plan fits?" go to TEMPLATE plan-tiles in over half the runs (passes 6/14; baseline without orders 7/8, provider alone without the template 7/8). Rewording the new manifest's examples didn't help (3/8), so it wasn't that one file: a longer template list makes DECIDE more template-happy on borderline requests, and any new use case would do the same. Fix, generic, in DECIDE's rules: coverage is full only when every need is met by the template's intent or a provider param; a need no param can express (the user's situation, "which one suits me") is a gap, so GENERATE. Result 8/8, then all evals 35/35 (decisions 23/23 twice, modify eval green).
  - **Client walkthrough to confirm F5:** Assistant → "show me my orders" (7 order tiles, newest first, "All 7 orders, newest first.") → "which of my orders were delivered?" (3 tiles, "3 of 7 orders with status Delivered.") → "orders over $100" → "did I buy any headphones?" (one order) → "my last 3 orders" → "I travel a lot, which plan fits?" still GENERATEs. Optional: Explorer → "show me the order history" → "make the status caps green" (REFINE on the new screen, no code).

---

## How we verify

**Acceptance is through the React client, never curl** (standing preference of the user).
Run the client (`cd client && npm run dev` → http://localhost:5176), open the **Chat** tab, type a prompt, and see the result.
pytest is a development aid and the parity safety net, but a phase isn't done until the client shows it working.

**Side-by-side trick for parity checks:** run Python on another port and point the client at it without touching code:
```
# Python on 8091 while Node keeps 8090
uv run python run.py --port 8091
# client, in another shell
AGUI_TARGET=http://localhost:8091 npm run dev      # bash
$env:AGUI_TARGET="http://localhost:8091"; npm run dev   # PowerShell
```
The Vite proxy reads `AGUI_TARGET` (see `client/vite.config.ts`). Restart the client to switch back.

---

## The wire contract (must match exactly)

Everything the client depends on is listed here. The source of truth is `agui/server.js` (server) and `client/src/Chat.tsx` lines ~150–200 (client parser).

### Request

`POST /agui/run`, `Content-Type: application/json`. The client sends **only**:

```json
{ "threadId": "thread_<uuid>", "runId": "run_<ms>", "messages": [{ "id": "u_<ms>", "role": "user", "content": "<text>" }] }
```

- Use only the **newest `role: "user"` message**. Earlier turns are restored from the checkpointer by `threadId`.
- If `threadId` or `runId` is missing, generate `thread_<uuid4>` / `run_<uuid4>`.
- **Since P6, a UI action** (a component's A2UI `event`, e.g. a plan's Choose button) is sent on the same `threadId` as the A2UI v0.9 client-to-server message in `forwardedProps`, with `messages: []`:
  `{ "threadId", "runId", "messages": [], "forwardedProps": { "a2uiAction": { "version": "v0.9", "action": { "name", "surfaceId", "sourceComponentId", "timestamp", "context" } } } }`.
  `context` arrives with bindings already resolved. The server records it in history as a `[UI action] <name> …` turn and merges its scalar context into the thread's `selections`. The response events are the same as for any turn.
- Since P5, `state.persona` (`"assistant"` | `"explorer"`) picks the persona policy; missing or unknown means `assistant`.
- ⚠️ Don't bind the body to `ag_ui.core.RunAgentInput` without checking its required fields. The client omits `state`, `tools`, `context` and `forwardedProps`, and a strict model will return **422**. Parse leniently.

### Response

Status 200 with these headers:
```
Content-Type: text/event-stream
Cache-Control: no-cache, no-transform
Connection: keep-alive
X-Accel-Buffering: no
```

Each event is one SSE frame: **`data: <json>\n\n`**, a single `data:` line followed by a blank line. The client splits on `\n\n` and parses the `data:` line, so **no multi-line data and no `event:` field is required**. JSON keys are **camelCase** (serialize the ag_ui models by alias and exclude `None`).

**Text turn** (router → `text`):
```
RUN_STARTED           { threadId, runId }
TEXT_MESSAGE_START    { messageId, role: "assistant" }     ← on responder's first token
TEXT_MESSAGE_CONTENT  { messageId, delta }                  ← one per token chunk
TEXT_MESSAGE_END      { messageId }
RUN_FINISHED          { threadId, runId }
```

**UI turn** (router → `ui`):
```
RUN_STARTED           { threadId, runId }
CUSTOM                { name: "status", value: { text: "Generating UI…" } }
CUSTOM                { name: "a2ui",   value: { a2ui: [ ...A2UI messages ], meta: { ... } } }
TEXT_MESSAGE_START    { messageId: <new id>, role: "assistant" }
TEXT_MESSAGE_CONTENT  { messageId, delta: "Here's the UI you asked for." }
TEXT_MESSAGE_END      { messageId }
RUN_FINISHED          { threadId, runId }
```
**Since F1 (post-P4):** `status` is sent **repeatedly**, and on text turns too. The router sends "Reading your request…"; the UI branch sends its stage ("Generating UI from the design system's components…", "Fixing N issues the design-system check found (attempt k of n)…") and re-sends it every second with the elapsed time appended ("… 12s"). The client shows the latest one until text or a surface arrives. Same event name and shape, so no client change.

If the gate never passes, **skip the `a2ui` event** and send the text trio with the apology instead:
`"I couldn't build a valid UI for that. Could you rephrase or simplify the request? (The generated layout didn't pass validation.)"`

**Errors:** on an exception, emit `RUN_ERROR { message }` (unless the client has disconnected), then close the stream.

**Client disconnect:** stop consuming the graph stream and **don't** emit `RUN_FINISHED`. (Node detects this on the *response* socket. In FastAPI, catch `asyncio.CancelledError` in the generator and/or poll `await request.is_disconnected()`.)

**Since P7, trace events** wrap the above: `STEP_STARTED`/`STEP_FINISHED { stepName }` for `decide`, `ground` and `build`, and each traced call (the decision, `guidelines.search`, `mcp.resolve_intent_to_schema`, data providers, `design_brief`, every `generate_a2ui` attempt, `guidelines.lint`, `guidelines.judge`) as `TOOL_CALL_START { toolCallId, toolCallName }` → `TOOL_CALL_ARGS { delta: <json args> }` → `TOOL_CALL_END` → `TOOL_CALL_RESULT { messageId, toolCallId, content: <json result with a human "summary">, role: "tool" }`. They are additive: a client that ignores them still works.

**Since P8:** the client sends `state: { persona }` on every run (header switch). An explorer ADAPT turn emits several `CUSTOM a2ui` events in one run (baseline first, then each variant as it passes), and a REFINE turn emits one. `meta.source.kind` is `"template"`, `"variant"` (`{id, base, rev}`) or `"generated"`, and `meta.card` (only for personas with `showRationale`) holds what the client's variant card shows: `{id, kind, label, base, rev, title, rationale, sources[{id,title}], changes[], flags[], missingData[], patch}`. New trace names: `propose_variants`, `variant.check`, `variant.repair`, `lineage.rebuild`; new steps `baseline`, `variants`, `rebuild`, `refine`. Additive: the assistant path is unchanged.

**Fields the client actually reads:** `type`, `delta`, `name`, `value`, `value.text`, `value.a2ui`, `value.meta.card` (P8), `message`. Everything else is informational, but keep it for parity.

`meta` (from `agent/uiGenerator.js`): `{ provider, model, attempts, graphRepaired, schemaChecked, unknownComponents }`. The client ignores it; keep it anyway, since it's useful in logs and later in the trace panel.

### Health

`GET /agui/health` → `{ "status": "ok", "phase": <n>, "endpoint": "/agui/run", "checkpointer": "postgres" | "memory" }`.
(Node also serves a debug page at `GET /`. **Don't port it**, since it's a debug aid only.)

### A2UI envelope (what the generator must emit)

```json
{ "a2ui": [
  { "version": "v0.9", "createSurface":    { "surfaceId": "main", "catalogId": "<catalog id>" } },
  { "version": "v0.9", "updateComponents": { "surfaceId": "main", "components": [ { "id": "root", "component": "Column", "children": ["a"] }, ... ] } },
  { "version": "v0.9", "updateDataModel":  { "surfaceId": "main", "path": "/", "value": { } } }
] }
```
Exactly one message key per message, a flat component list, exactly one `id: "root"`, props inline, bindings as `{ "path": "/json/pointer" }`, list templates as `children: { "path", "componentId" }`. The generator always names its surface `"main"`, and **the client deliberately rewrites `surfaceId` and `catalogId`** per turn (`normalizeA2ui` in `Chat.tsx`). Don't "fix" this server-side.

---

## Target layout

```
templates/<id>/               ← P5: curated A2UI templates (surface.json + manifest.json), authored by designers
data/                         ← P5: illustrative mock data read by data providers
server/                       ← all new Python code lives here
  pyproject.toml              uv project, requires-python >=3.12
  .env.example                documents server-only overrides (DATABASE_URL → a2ui_py)
  run.py                      entry point: sets the Windows event-loop policy, then uvicorn.run
  app/
    main.py                   FastAPI app, lifespan (checkpointer, graph), routes
    config.py                 settings: root .env, then server/.env overrides
    log.py                    readable one-line flow logs (mirror src/logger.js style)
    agui_bridge.py            graph.astream_events → AG-UI events (the contract above)
    graph/
      playground.py           the one graph: router, responder, ui_generator nodes + build_graph()
                              (P5 turns the router into DECIDE → POLICY → …; "assistant" is a persona, not a file)
    generation/
      llm.py                  JSON-mode call, reasoning-model params, tolerant JSON parse
      prompt.py               build_system_prompt(catalog), byte-identical to Node's
      graph_check.py          validate_and_repair_graph (orphans, root wiring)
      gate.py                 jsonschema validator gate
      generate.py             generate_validated_a2ui: generate → check → gate → repair loop
    grounding/
      catalog.py              load catalog.json once, cache
      layout.py               Column/Row/List/Divider schemas + merge_basic_layout
    state/
      checkpointer.py         AsyncPostgresSaver if DATABASE_URL, else InMemorySaver
    templates/                P5: TemplateStore interface + FileTemplateStore
    data/                     P5: data provider registry (field schemas + mock readers)
    decide/                   P5: decide.py (structured decision), policy.py (persona rules)
    verify/                   P7: lints.py (hard rules), judge.py (soft rules)
    explore/                  P8: patching.py (JSON Patch over a component view), variants.py (propose,
                              verify, repair per variant), lineage.py (what's on screen, rebuild a surface)
    graph/explore.py          P8: the adapt and refine nodes; graph/state.py holds GraphState
  config/
    personas.json             P5: allowed strategies, variants, conflict handling per persona
  evals/
    decisions.jsonl           P5+: prompt + persona → expected strategy/template (run with -m eval)
  tests/
    fixtures/                 parity fixtures dumped from the Node implementation
    test_gate.py              port of test/catalogSchemas.test.mjs + strictness cases
    test_prompt_parity.py     Python prompt == Node prompt, byte for byte
    test_graph_check.py       parity with src/validateGraph.js on fixtures
    test_contract.py          event order/shape for text and UI turns (fake LLM)
```

### Node → Python map

| Node (reference, deleted in P4) | Python | Notes |
|---|---|---|
| `agui/server.js` | `app/main.py`, `app/agui_bridge.py` | Contract above. Filter text deltas by `metadata.langgraph_node == "responder"` |
| `agent/graph.js` | `app/graph/playground.py` | Router prompt and fallback-to-`text` on error, verbatim |
| `agent/uiGenerator.js` | `app/generation/generate.py` | `A2UI_MAX_REPAIRS` (default 2), repair prompt text verbatim |
| `agent/checkpointer.js` | `app/state/checkpointer.py` | Call `setup()` once. Keep the saver open for the app lifetime (FastAPI lifespan) |
| `src/localCatalog.js` | `app/grounding/catalog.py` | Same `{catalogId, components, defs, names}` shape |
| `src/basicLayoutCatalog.js` | `app/grounding/layout.py` | Copy the four schemas **verbatim** (as a JSON/dict literal) |
| `src/systemPrompt.js` | `app/generation/prompt.py` | **Byte parity**, enforced by test. Build once, cache |
| `src/llm.js` | `app/generation/llm.py` | See *Gotchas* 8 |
| `src/validateGraph.js` | `app/generation/graph_check.py` | Parity via fixtures |
| `src/catalogSchemas.js` | `app/generation/gate.py` | Semantics change, see *Gotchas* 1–3 |
| `src/logger.js` | `app/log.py` | Keep the readable step-by-step trace |
| `src/mcpClient.js` | P7: `app/grounding/mcp.py` | Via `langchain-mcp-adapters` |
| `src/index.js` (`/generate`) | Decision **D1** | |
| `test/catalogSchemas.test.mjs` | `tests/test_gate.py` | |

### Configuration

Python loads the **root `.env`** (shared keys) and then **`server/.env`** (overrides). Only the database differs.

| Key | Default | Used for |
|---|---|---|
| `OPENAI_API_KEY` | (required) | LLM |
| `OPENAI_MODEL` | `gpt-4o` | responder + generator |
| `ROUTER_MODEL` | `gpt-4o-mini` | router classifier (non-streaming) |
| `OPENAI_MAX_TOKENS` | `6000` | generator completion cap |
| `LLM_PROVIDER` | `openai` | `openai` \| `anthropic` |
| `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` | Node's defaults | provider switch (keep parity) |
| `DATABASE_URL` | unset → in-memory | **`server/.env` sets `postgresql://a2ui:a2ui@localhost:5432/a2ui_py`** |
| `A2UI_MAX_REPAIRS` | `2` | repair loop bound |
| `LOCAL_CATALOG_PATH` | `<repo>/node_modules/@shadab5114/pds-core/catalog.json` | catalog source |
| `AGUI_PORT` | `8090` | server port (`run.py --port` overrides) |
| `MCP_URL` | from `.env` | P7 |
| `RAG_URL` | from `.env`: `http://127.0.0.1:5000/query` | P7 (D2); unset → RAG bypassed |
| `RAG_COLLECTION` | `design_system` | P7 (D2): the `collection_name` sent with every query |
| `RAG_TIMEOUT` | `30` | P7 (D2): seconds per RAG call (it writes an answer, so it is slower than plain retrieval) |
| `TEMPLATES_DIR` | `<repo>/templates` | P5 |
| `DATA_DIR` | `<repo>/data` | P5 (mock data for providers) |

`.env` holds secrets. Never print values, and never commit `server/.env`. Check that it's covered by `.gitignore`.

---

## Gotchas already confirmed in this repo

1. **The validation semantics change, and that's intended.** All 35 components in `catalog.json` declare `unevaluatedProperties: false`. Node's Zod schemas are lenient (undeclared props are ignored) and describe *resolved* props, so Node needs a "binding-aware" hack that ignores type errors when a value is `{ "path": ... }`. `catalog.json` describes the *wire* format: dynamic props are typed `DynamicString`, `DynamicBoolean` and so on, which accept bindings natively. **So the Python gate needs no binding hack, and it rejects undeclared props.** Expect the repair loop to run a bit more often at first. That reflects the catalog's actual contract, not a regression. `action`, `checks` and `weight` are declared in `$defs/CatalogComponentCommon`, so interactivity still validates.
2. **Validating one component:** every `$ref` in `catalog.json` is local (`#/$defs/...`). Build one validator per component from `{"$defs": catalog["$defs"], **catalog["components"][name]}` using `Draft202012Validator`, and cache them. Validate the **whole node** (`id`, `component` and the rest). Unlike the Zod path, no wrapper-key stripping is needed. jsonschema nests errors under `allOf`, so collect **leaf errors** (walk `error.context`) and format them as `path: message`. These strings go straight into the repair prompt. ⚠️ **Confirmed in P2:** per the spec, a *failed* `allOf` branch drops its annotations, so one bad enum makes `unevaluatedProperties` also flag every valid prop of that branch (`'children', 'component', 'size' were unexpected`). That would mislead the repair prompt, so `gate.py` rewrites that error to list only props the component's schema never declares (and drops it when there are none).
3. **The layout components aren't in `catalog.json`.** `Column`, `Row`, `List` and `Divider` come from `basicLayoutCatalog.js`, and their `$ref`s point at `https://a2ui.org/.../common_types.json`. For parity, **don't schema-validate them**: report them in `unknownComponents`, as Node does. Never fetch that URL at runtime. Keep the refs as-is inside the prompt text (prompt parity depends on it).
4. **Separate database.** Create it once: `docker exec a2ui-postgres createdb -U a2ui a2ui_py`. Old Node threads won't carry over, and that's fine.
5. **Windows + async psycopg:** psycopg's async mode can't run on the Proactor event loop, which is the Windows default. ⚠️ Since uvicorn 0.36 the loop comes from a **loop factory**, not the asyncio policy, so setting `WindowsSelectorEventLoopPolicy` is silently ignored (`loop="auto"`/`"asyncio"` still gives Proactor on Windows). **Done in P0:** `run.py` passes `loop="app.loops:selector_loop_factory"`. A custom import string is used *as* the factory (a zero-arg callable returning a loop). Startup logs the loop class, currently `_WindowsSelectorEventLoop`. Confirm again in P1 once psycopg is in.
6. **Custom events:** use `adispatch_custom_event` (from `langchain_core.callbacks`) inside nodes and consume `graph.astream_events(..., version="v2")`. They arrive as `event == "on_custom_event"` with `name` and `data`. Python ≥3.11 propagates the run config automatically; don't drop below 3.12.
7. **Router tokens must not leak.** The router is an LLM call too. Only events whose `metadata["langgraph_node"] == "responder"` become `TEXT_MESSAGE_*` deltas. (`on_chat_model_start` → START, `on_chat_model_stream` → CONTENT, where chunk content may be a string or a list of parts.)
8. **LLM params by model family** (`src/llm.js`): reasoning models (`gpt-5*`, `o<digit>*`) take `max_completion_tokens` and **no temperature**. Other models take `temperature=0.2` and `max_tokens`. The router and responder use `temperature=1` so one code path works for both. Port the tolerant JSON parse: try direct, then a ```json fence, then the first `{` to the last `}`.
9. **UI generation isn't token-streamable.** It's one non-streamed call plus possible retries, which means several silent seconds. That's why `status` is sent first. Keep it.
10. **The catalog lives in `node_modules`.** A root `npm install` is required, and it needs `NODE_AUTH_TOKEN` for GitHub Packages (`.npmrc`). If the file is missing, fail at startup with a clear message saying so.
11. **Port clash:** Node's `npm run agui` also binds :8090. Stop it before starting Python there, or use the side-by-side trick.

---

## Phases

### P0: Scaffold, stub stream through the real client

**Build**
- `server/` as a uv project. Dependencies: `fastapi`, `uvicorn[standard]`, `ag-ui-protocol`, `python-dotenv` (or `pydantic-settings`), `pytest`, `pytest-asyncio`, `httpx`. Add the rest in the phase that needs them.
- `run.py` with the Windows loop policy and `--port`. `app/config.py`, `app/log.py`.
- `POST /agui/run` streams a **hard-coded** text turn (`RUN_STARTED` → START → a few CONTENT deltas → END → `RUN_FINISHED`), following the contract exactly.
- `GET /agui/health`.
- Root `package.json` script: `"agui:py": "cd server && uv run python run.py"`. Leave `agui` (Node) as it is for now.
- Add `.venv/`, `__pycache__/` and `.pytest_cache/` to the root `.gitignore`. (`server/.env` is already ignored by the existing `.env` pattern.)

**Done when:** with Node stopped and `npm run agui:py` running, the client's Chat tab shows the stub reply streaming in, with no console errors.

### P1: Text branch with durable memory

**Build**
- Dependencies: `langgraph`, `langchain-openai`, `langgraph-checkpoint-postgres`, `psycopg[binary,pool]`.
- `graph/playground.py`: router (always returns `text` in this phase) → responder (streaming `ChatOpenAI`, system prompt verbatim from `agent/graph.js`).
- `state/checkpointer.py`: `AsyncPostgresSaver.from_conn_string(DATABASE_URL)` inside the FastAPI lifespan, `await setup()`, and a fallback to `InMemorySaver` when `DATABASE_URL` is unset.
- `agui_bridge.py`: map `astream_events` to AG-UI events, with the responder filter and disconnect handling.
- `server/.env` pointing at `a2ui_py`. Create the database.

**Done when:** in the client, you tell it your name, then ask for it back, and it remembers. **Restart the Python server** and ask again on the same chat: it still remembers. "New chat" forgets. Startup logs show `checkpointer: postgres` and a Selector event loop.

### P2: Catalog, prompt, validator gate (parity via tests)

This is the one phase verified by tests rather than the client. P3 makes it visible.

**Build**
- Dependency: `jsonschema`.
- `grounding/catalog.py`, `grounding/layout.py` (`merge_basic_layout`).
- `generation/prompt.py`: port `buildSystemPrompt` faithfully.
- `generation/graph_check.py`: port `validateAndRepairGraph`, including the in-place repairs.
- `generation/gate.py`: `validate_component(node)` and `validate_a2ui_document(doc)` returning the same shapes as Node (`{ok, component, id, issues, unknown}` / `{valid, checked, unknownComponents, failures}`).
- **Parity fixtures (do this before touching P4):** add a small Node script (e.g. `scripts/dump-parity-fixtures.mjs`) that writes:
  - `server/tests/fixtures/system_prompt.node.txt`: Node's `buildSystemPrompt(mergeBasicLayout(loadLocalCatalog()))`
  - `server/tests/fixtures/graph_check/*.json`: input docs plus Node's `validateAndRepairGraph` result (repaired doc, warnings, errors). Include orphans, a missing root, a bare `{path}` root children, duplicate ids and a list template.
- Tests:
  - `test_prompt_parity.py`: the Python prompt equals the Node fixture **byte for byte**.
  - `test_graph_check.py`: identical results on every fixture.
  - `test_gate.py`: port all 7 cases from `test/catalogSchemas.test.mjs`. They should all pass unchanged: `action` is declared, and `Column` is reported as unknown, not failed. **Add** these cases, which document the intended strictness:
    - an undeclared prop (e.g. `"foo": 1` on a `Button`) is **rejected**
    - a binding on a dynamic prop (`InputField.value: {"path": "/x"}`) is **accepted** without any hack

**Done when:** `uv run pytest` is green, including byte-identical prompt parity.

### P3: UI branch, generated surfaces in the client

**Build**
- Router: the real LLM classifier (`ROUTER_MODEL`, non-streaming, prompt verbatim, any error → `text`).
- `generation/llm.py`: JSON mode, per-family params (gotcha 8), tolerant parse, provider switch.
- `generation/generate.py`: `generate_validated_a2ui(user_prompt)` runs generate → `graph_check` → `gate` and repairs up to `A2UI_MAX_REPAIRS` times. The repair prompt is verbatim from `uiGenerator.js`. Returns `{ok, a2ui, meta}` or `{ok: false, errors, attempts, last_doc}`.
- `ui_generator` node: `status` → `a2ui` + caption, or the apology on failure. It appends a compact `AIMessage` (caption or apology) to state, **not** the surface.
- `tests/test_contract.py`: with a fake LLM, assert the exact event sequence for a text turn, a UI turn and a gate-failure turn.

**Done when**, in the client:
- "what is a design system?" streams text
- "show me a sign-up form with email, password and a submit button" renders a real PDS surface inline
- a second UI request in the same chat renders a **new** surface, and the first one stays intact
- the server log shows attempt counts. At least once, you've seen a rejected attempt followed by a repaired, valid one (or simulated it by lowering `A2UI_MAX_REPAIRS` to 0 against a bad prompt and seeing the apology text)

### P4: Parity sign-off, retire Node

**Build**
- Resolve **D1** with the user and implement it.
- Walk through a short parity script in the client, against Node and then against Python (side-by-side trick): text turn, memory recall, form UI, list UI, modal UI (see the interactivity notes in `src/systemPrompt.js`), gate failure. Record any differences in the phase log. Fix them, or accept them explicitly (for example, stricter validation).
- Switch scripts: `npm run agui` starts Python. Remove the Node-only scripts.
- Delete `agent/`, `agui/`, `src/`, `test/*.mjs` and the Node-only dependencies from the root `package.json`. **Keep** `@shadab5114/pds-core` at the root: Python reads its `catalog.json`.
- Update `README.md` (run instructions) and mark `A2UI-BACKEND-ARCHITECTURE.md` as superseded for the backend stack, keeping it for its concepts.

**Done when:** with no Node server process running, every client tab works against Python only.

---

### The decision architecture behind P5–P8

The goal: for any **prompt + persona**, the backend decides whether to **reuse a curated template or create new UI from the catalog**, and when it creates, it is **creative but grounded in the design guidelines**.

**Curated screens are static generative UI.** Plan tiles, plan details and add-ons are **pre-authored A2UI templates**: the design team owns the layout, and the agent selects a template and fills in the data. Both personas pull from the **same library**. Static and declarative share one pipeline (renderer, validator gate, wire events). A template is simply A2UI that a person wrote.

#### One graph; the persona is a policy, not a separate graph

Both personas run the **same pipeline**. What differs is what the agent is *allowed* to do, and that's declared as data in `server/config/personas.json`, not buried in prompts:

```json
{
  "assistant": { "strategies": ["TEXT", "TEMPLATE", "GENERATE"],                    "variants": 1, "onGuidelineConflict": "repair", "showRationale": false },
  "explorer":  { "strategies": ["TEXT", "TEMPLATE", "ADAPT", "GENERATE", "REFINE"], "variants": 3, "onGuidelineConflict": "ask",    "showRationale": true }
}
```

This replaces the earlier idea of separate Assistant and Explorer graphs.

#### Five strategies (the dial, made concrete)

| Strategy | What the backend does | Dial position |
|---|---|---|
| `TEXT` | Answers in prose (streamed, as today) | none |
| `TEMPLATE` | Picks a curated template and fills **data only** from providers | Pinned (static) |
| `ADAPT` | Takes a curated template and applies **JSON Patches** that close the gaps in the request, producing N variants | Composed (static + declarative deltas) |
| `GENERATE` | Composes **new UI from the catalog**, grounded in guidelines and patterns | Generated (declarative) |
| `REFINE` | Patches a surface **already on screen** (e.g. "badge on option 3") | Composed |

#### The pipeline: LLM proposes, policy disposes

```
prompt + persona + what's on screen
   │
   ▼
DECIDE    one structured-output call (small model): { intent, strategy, templateId?, coverage, gaps[], target?, reason }
   │        matched against template manifests filtered by persona
   ▼
POLICY    plain code: is that strategy allowed for this persona? If not, fall back
   │        (e.g. assistant + ADAPT → GENERATE, or TEMPLATE as-is if the gaps are minor)
   ▼
GROUND    (ADAPT / GENERATE / REFINE only) RAG + MCP → a short DESIGN BRIEF: chosen pattern,
   │        components, rules that apply, each with a citation
   ▼
BUILD     TEMPLATE: fill data · ADAPT/REFINE: patches from the brief · GENERATE: A2UI from the brief
   ▼
VERIFY    1. schema gate (catalog.json, as in P2)   2. guideline gate (hard rules as lints + soft rules via a judge)
   │        fail → repair with the cited rule, or per policy ask the user (interrupt)
   ▼
RESPOND   surface(s) + reason + sources   (reason and sources feed the trace panel)
```

Why this shape:
- **The decision is a structured object, not a vibe.** `strategy`, `coverage` (`full` / `partial` / `none`) and `gaps` are explicit. The `gaps` become the input to ADAPT ("what the template doesn't cover yet"). Use `with_structured_output(<Pydantic model>)` here. These schemas are small and work with strict structured outputs, unlike A2UI documents, which stay in JSON mode.
- **Policy lives in code, not prompts.** The LLM can propose anything. Plain code enforces what each persona may do, so behavior is predictable and testable.
- **Creativity has a place and a check.** Divergent thinking happens in the **brief** (higher temperature, and the explorer can consider 2–3 directions). Convergent building happens in **BUILD** (low temperature). The **guideline gate** is what makes creative output safe to show. MCP should supply **approved patterns** (compositions), not just components, so the agent is creative at the pattern level and safe at the component level.
- **Everything the agent decided is visible:** `reason`, the brief and its citations become thinking steps and trace-panel entries. That's the demo's thesis.

#### Examples the decision step must get right (the start of the eval set)

| Prompt | Persona | Expected | Why |
|---|---|---|---|
| "show me the plans" | assistant | `TEMPLATE plan-tiles` | full match |
| "unlimited plans under $60" | assistant | `TEMPLATE plan-tiles` + provider filter | same UI, different data |
| "I travel a lot, which plan fits?" | assistant | `GENERATE` (comparison pattern, grounded) | no template covers it |
| "what's the difference between 5G and LTE?" | either | `TEXT` | no UI needed |
| "show me plan details" | explorer | `TEMPLATE plan-tiles` (baseline) | full match |
| "add network coverage info to the plan view" | explorer | `ADAPT plan-tiles` ×3 | partial match; explorer may change structure |
| "add a badge on option 3" | explorer | `REFINE var-3` | targets a surface on screen |
| "design an onboarding screen for new customers" | explorer | `GENERATE` ×3 | no template |

**Decision evals:** keep these in `server/evals/decisions.jsonl` (`{prompt, persona, screen?, expect: {strategy, templateId?}}`) and run them with a real model on demand (`uv run pytest -m eval`), **not** in the default test run. Prompt, catalog and template changes can silently shift decisions; this is how you notice. Grow the set whenever a decision surprises you.

**Data never comes from the LLM.** Plan names, prices and features come from **data providers** (tools reading mock JSON now, a real API later). The LLM chooses templates, provider params, patches and compositions, never values. If a request needs data a provider doesn't expose (e.g. network coverage), the agent **says so** instead of inventing it.

### P5: Static generative UI, shared curated template library (outline)

**Build**
- **Templates** at repo root `templates/<id>/` (content, not code, so designers can author them, e.g. with the `figma-to-a2ui` skill):
  - `surface.json`: A2UI messages with **data bindings**, surface id `"main"`. Use list templates for repeated tiles: `children: { "path": "/plans", "componentId": "plan-tile" }` with relative pointers inside the tile.
  - `manifest.json`:
    ```json
    { "id": "plan-tiles", "version": 1, "title": "Plan tiles",
      "intent": "Show the available mobile plans side by side",
      "personas": ["assistant", "explorer"],
      "data": { "provider": "plans.list", "params": { "segment": "string, optional" } },
      "suggestedNext": ["plan-addons"] }
    ```
- **Starter content (create it in this phase):** two templates, `plan-tiles` and `plan-addons` (P6 needs the second), plus illustrative mock data (`data/plans.json`, `data/addons.json`). Build them from PDS components in the catalog. If the user has Figma frames for these screens, use the `figma-to-a2ui` skill instead of hand-writing them. Mock data is **illustrative**: invented plan names and prices, clearly not real carrier pricing.
- **Store:** `app/templates/store.py` with a `TemplateStore` interface and a `FileTemplateStore` over `TEMPLATES_DIR`. An object store is **D4**, later.
- **Data providers:** `app/data/providers.py`, a registry mapping a name to `(params) -> dict`, reading **illustrative** mock JSON from `DATA_DIR` (e.g. `data/plans.json`). **Each provider declares its field schema** (which fields exist). P8 depends on this.
- **The decision pipeline, first slice** (see *The decision architecture*). The router from P3 becomes **DECIDE → POLICY → BUILD → VERIFY**, with strategies `TEXT`, `TEMPLATE` and `GENERATE`:
  - `app/decide/decide.py`: one structured-output call over the persona-filtered manifest list, returning `{intent, strategy, templateId, coverage, gaps, reason}`
  - `app/decide/policy.py` + `server/config/personas.json`: enforces allowed strategies and fallbacks. Persona comes from `RunAgentInput.state.persona` if the client sends it, else `assistant`.
  - `TEMPLATE` build (`render_template`): loads the surface, calls the provider with params from DECIDE, appends `updateDataModel { path: "/", value: <data> }`, runs the **same gate**
  - `GENERATE` build: the existing P3 generator (grounding arrives in P7)
- `meta.source` on every surface: `{ "kind": "template", "id": "plan-tiles", "version": 1 }` or `{ "kind": "generated" }`, plus `meta.decision` (strategy + reason).
- **Tests:** every template's `surface.json` passes the gate, every manifest's provider exists, and **every binding path in a template exists in its provider's field schema**. A broken template fails CI, not the demo. The policy module gets unit tests (every disallowed strategy falls back correctly).
- **Evals:** start `server/evals/decisions.jsonl` with the assistant rows from the examples table.

**Done when**, in the client:
- "show me the plans" renders the curated plan tiles with mock data, the **layout is identical across repeated runs**, and the log shows `decision: TEMPLATE plan-tiles@1 (reason…)`
- "unlimited plans under $60" reuses the same template with filtered data
- "I travel a lot, which plan fits?" produces **generated** UI, and the log shows why no template was chosen
- "what's the difference between 5G and LTE?" streams text

### P6: `userAction` round-trip + multi-step flows (outline)

Close the loop: clicking a control in a surface reaches the agent, and the agent decides the next screen.
- Client: `Chat.tsx` currently only `console.log`s actions from the `MessageProcessor` action sink. It must POST them back to `/agui/run` on the same `threadId`. **This is the first intentional client change.**
- Server: accept an action-shaped input alongside `messages` and resume the checkpointed graph. Template actions carry an event name and context (e.g. `select_plan { planId }`), which update graph state (`selectedPlan`). The agent then decides the next step, using `manifest.suggestedNext` as **hints, not a hard-coded state machine** (the agent chooses, which is what makes it agentic), and renders it via `render_template` with provider params from state.
- **Done when**, in the client: "show me the plans" → click **Choose** on a plan → the add-ons for **that** plan appear.

### P7: Grounding tools, MCP + RAG (outline; needs D2 and D3)

- `grounding/mcp.py` via `langchain-mcp-adapters` (`MultiServerMCPClient`). `grounding/rag.py` as a LangChain `tool()` over `httpx`.
- **Contract for every grounding tool: return `{ "answer": ..., "sources": [...] }`.** Citations make the trace panel and guideline flags possible, so don't skip them.
- **GROUND step:** for `GENERATE` (and later `ADAPT`/`REFINE`), produce a **design brief** before building: chosen pattern, components, applicable rules, each with a citation. BUILD generates from the brief.
- **Guideline gate** in VERIFY (`app/verify/`): **hard rules as deterministic lints** (`lints.py`) and **soft rules via an LLM judge** (`judge.py`) that is given the retrieved rules. Needs **D5**. On failure: repair with the cited rule (assistant), or ask per policy (explorer, P8).
- Bridge **all** tool activity, grounding queries and template picks alike, to AG-UI `TOOL_CALL_START`, `TOOL_CALL_ARGS`, `TOOL_CALL_END` and `TOOL_CALL_RESULT`. Surface the DECIDE `reason` and the brief as thinking steps (`STEP_STARTED` / `STEP_FINISHED`). The client needs a trace panel to show them (client change).
- **Done when**, in the client: "I travel a lot, which plan fits?" shows in the trace panel the decision and its reason, the guideline queries with sources, and the brief; the generated UI follows the brief; and a deliberately rule-breaking request is caught by the guideline gate and repaired.

### P8: Explorer, template-seeded variants + patch refinement (outline)

The designer's real workflow: **start from production, explore deltas.**
- **Persona switch** in the client, sent as `RunAgentInput.state.persona`. Same graph; the **explorer policy** unlocks `ADAPT` and `REFINE`, 3 variants, and "ask" on guideline conflicts.
- **Baseline:** "show me plan details" → `TEMPLATE`, exactly as for the assistant, labelled `Baseline · plan-tiles@1`.
- **`ADAPT`:** "add extra info to the plan view". DECIDE returns `coverage: partial` with `gaps` (e.g. "no coverage info"). Then:
  1. GROUND (P7) turns the gaps into a brief: what the guidelines say about this change
  2. BUILD asks the LLM for **N JSON Patches against the baseline** (RFC 6902, `jsonpatch`), each with a rationale and sources. **Patches, not full surfaces**, so unchanged parts stay byte-identical to production and every variant is a readable diff.
  3. VERIFY runs both gates on each patched result, and each variant is emitted as soon as it passes (don't wait for all N)
- **Lineage** in graph state (persisted by the checkpointer):
  `surfaces: { "var-2": { "base": "plan-tiles@1", "patches": [...], "rationale": "...", "sources": [...] } }`.
  **`REFINE`** ("add a badge on option 3"): DECIDE resolves `target` from what's on screen, and the new patch is **appended to that variant's chain**. Other variants are untouched. **Every node needs a stable `id`** (already required by A2UI).
- **Evals:** add the explorer rows from the examples table to `decisions.jsonl`.
- **Data contract rule:** a variant may bind only to fields in the provider's field schema. If the instruction needs data that doesn't exist (e.g. "show network coverage"), the agent **says so** ("this variant needs a new data field `coverage`") instead of inventing values. That's useful design feedback in its own right.
- **Guideline conflicts:** when a change contradicts a cited rule (e.g. DS-207 on badges), pause for the designer's decision, preferably with a LangGraph `interrupt()` resumed via `RunAgentInput.resume`, or apply and flag with the citation and an alternative.
- **Wire:** unless **D6** (protocol alignment) has been done, emit refinements as `CUSTOM { name: "a2ui_patch", value: { target, patch } }`.
- **Client:** gallery showing the baseline plus variants, with rationale, sources and what changed.
- *Optional closing loop:* "promote variant" writes it as a **new template version candidate** in `templates/` for design-team review, never auto-published. The explorer proposes, the design team approves, and the assistant persona uses it.
- **Done when:** the designer flow runs end to end in the client: baseline → 3 grounded variants → refine one → the others are unchanged.

**As built (2026-09-19):**
- **Graph:** `decide → adapt` and `decide → refine` (`app/graph/explore.py`). POLICY allows ADAPT only with a usable template and REFINE only with a `target` that is on screen, falling back otherwise. DECIDE got a `target` field, explorer-only rules, and the thread's on-screen list (`lineage.screen_lines`, each line with its card label and "option N" alias).
- **ADAPT:** it renders the baseline and emits it first. Then GROUND runs the guideline search and MCP on the request plus DECIDE's gaps. There is **no separate design brief**: each variant carries its own rationale and citations, which saves a model call. Next, one JSON-mode call proposes N variants, each as `{title, rationale, sources, missingData, patch}`. Each variant then gets verified and repaired **on its own** (the patch applies, then graph check, schema gate, hard-rule lints, the data contract, and the judge whose findings become flags). Variants are emitted in the order they pass (`asyncio.as_completed`) and numbered in that order.
- **Patches** address a view `{"components": {id: {...}}}`, not the A2UI message list (index paths are fragile for a model to write). Only `/components/...` may change, never the data. The prompt carries only the schemas the screen uses, the MCP suggestions and a few common components, plus their `$defs` (~38K chars against the generator's 147K).
- **Data contract:** every binding in a variant must be a provider field (`field_matches`), and the prompt forbids repurposing a field. This was seen live: before that rule, all three "network coverage" variants bound `hotspotLabel` as coverage. A variant that needs data reports it as `missingData` and may show a neutral placeholder ("Coverage details: data needed"); the caption says which field is missing.
- **REFINE = modify what's on screen** (`app/explore/modify.py`, reworked at the user's suggestion). It takes the target surface as it is now (the latest one when none is named; state `last_surface`, and POLICY falls back to it), sends its **complete component list** plus the request to the model, and gets back **only what changes**: `update` (props merged in), `add`, `remove`, `newState` (UI state for new inputs: "", booleans, 0, null or [] only, never content) and `split` (code gives particular list items their own copies, so the model never writes copies). Code applies the reply. It then runs the graph check, schema gate, hard-rule lints, the data contract (bindings must exist in the surface's own data), the targeting check and a stray-component check, sends any errors back for repair, and **computes the diff** for the card, the lineage and the judge. The judge sees only the change, and findings the surface already had are dropped. The data model never passes through the model's reply. This works on **any** surface, including generated UI, so **the assistant persona got REFINE too** (card chrome stays explorer-only).
- **Generic, not plan-specific (user priority 2026-09-19: generality, then accuracy, then speed).** The model prompts (DECIDE, ADAPT, modify, judge) carry only neutral examples; plans and add-ons are just the demo's content. **Accuracy eval on non-plan screens:** `tests/test_modify_eval.py` (`uv run pytest -m eval tests/test_modify_eval.py -s`) runs 11 real-model modify cases on an order list, a settings form, a product grid, a status dashboard and the plans screen. Every check is code: the right list items changed and only those, nothing else touched, no data copied as text, and new inputs bound to new state. Result: **11/11 twice, median ~3.7 s**. Replying with changes only was A/B'd against returning the whole list: equal accuracy (10/11 each, before the fixes below), 2–20× faster (split of 5 rich tiles: ~4 s vs ~80 s), so the whole-list mode was removed. Fixes the eval drove: a code-made copy that the model also writes out is taken as a replacement; unplaced components are sent back for repair instead of hung off the root; user-given wording and UI labels are allowed as literal text (the model had refused "add a line saying …").
- **End to end, real graph:** "make the Best value cap red" 45.8 s → **18.8 s** (decide 3.7, modify 4.9, judge ~10); a button rename ~13 s (decide ~4.8, modify 2.7, judge 5.8). **The judge is now the slowest step** (next lever: a judge eval first, then a faster judge model or a smaller judge input).
- **Lineage** lives in state `surfaces` (checkpointed): one record per surface shown (`baseline-N`, `var-N`, `ui-N` for generated UI) with its current `doc`, plus what changed at each revision in `patches`. Refining a baseline starts a new variant, so production is never edited.
- **Explorer GENERATE** also flags soft-rule conflicts instead of repairing them (`generate_validated_a2ui(repair_soft=False)`), and its card shows the brief's pattern. It is still **one** surface, not ×3; see F3.
- **Client:** a persona switch in the Chat header, and `VariantCard.tsx` around every surface whose meta has a `card`.
- **Evals:** 5 explorer rows, 15/15 twice. Two wording fixes came out of them: "show me plan details" first went to ADAPT and then to plan-addons (fixed with an explicit rule plus plan-tiles' manifest intent and an example), and "option 3" meant the third plan tile on the baseline (fixed with card labels and "option N" aliases in the screen list).
- **Fixed from the first client run:**
  - *"Make the Best value plan's cap red" turned every tile red.* The tiles are one list-template component, and `cap.backgroundColor` is a plain enum that can't be bound, so a change to the template hits every plan. The first fix made the agent decline, which the user rightly rejected. The second added an `unroll` patch op; it is still what ADAPT's patch variants use. The third is REFINE as described above: the model splits the list itself, guided by `data.lists` (each item's id, name, badge, for targeting only). A split variant is fixed to the items shown now.
  - The model declares `targets` (`all` / `some` / `screen`). A `some` result that statically changes a list-item component is rejected in code (`targeting_errors`) and goes back for repair. `blocked` remains for changes that truly need missing data or props. Change lines name split copies by item ("plan-tile-2 (Unlimited Go).cap.backgroundColor: changed → "red"") and mark static list-item edits "(applies to every item in /plans)".
  - *DS-204 was flagged on a cap-colour variant.* All five plans are badged on the approved screen, so the judge was reviewing production, not the change. The judge now gets the change list with "judge only what the change introduces" (`judge(..., change=...)`), and the base screen is judged in the background while variants are proposed. Findings the base screen already has are dropped from variants (trace: "already on the base screen, not flagged").
- **Evals:** 17 rows, 17/17. Two new REFINE rows: the assistant modifying the UI it just generated, and the cap-colour request. One run sent "I travel a lot, which plan fits?" to TEMPLATE, but it passed 3/3 in isolation and the next full run was 17/17: DECIDE on `gpt-5-mini` is a little noisy there.
- **Client walkthrough to confirm P8:** Explorer → "show me plan details" (baseline card) → "change the color of cap from black to red for best value plan" (a "Variant 1" card with only Unlimited Go red) → "add network coverage info to the plan view" (baseline + up to 3 variant cards, each saying it needs a `coverage` field) → "on variant 2, make the badge say Recommended" (a new "Variant 2 · rev 2" card, and the caption lists the unchanged surfaces) → switch to Assistant → "show me a sign-up form", then "make the button say Join now" (the same form, button renamed, no card chrome).

---

## Commands

```bash
# infra (Docker Desktop must be running)
npm run db:up
docker exec a2ui-postgres createdb -U a2ui a2ui_py     # once

# server
cd server && uv sync
npm run agui                          # from the repo root: :8090 (= cd server && uv run python run.py)
uv run python run.py --port 8091      # a second instance, e.g. side-by-side comparisons
npm test                              # from the repo root (= cd server && uv run pytest)
UPDATE_SNAPSHOTS=1 npm test           # after an INTENTIONAL catalog/prompt change (bash)

# client
cd client && npm run dev              # http://localhost:5176 → Chat and Generate UI tabs

# docs pages
npm run docs:genui
```

## Out of scope

Redis, BullMQ, auth, deployment and containers for the server, the iOS renderer, running the decision evals in CI (they run on demand), and changes to the design system package itself.

---

## Phase log

Add one line per completed phase: date, phase, what was verified in the client, and any deliberate differences from Node.

- 2026-09-19: Plan written. Node phases 0–4 are the reference implementation.
- 2026-09-19: Design refined with the user: curated screens are static generative UI (pre-authored A2UI templates) shared by both personas; persona = edit rights; Explorer variants are patches on the template, not from-scratch generations. Phases renumbered P5–P8.
- 2026-09-19: Decision architecture added: one graph with persona policy (replaces separate Assistant/Explorer graphs); DECIDE → POLICY → GROUND → BUILD → VERIFY → RESPOND; five strategies (TEXT, TEMPLATE, ADAPT, GENERATE, REFINE); design brief + guideline gate for grounded creativity; decision evals. New open decision D5.
- 2026-09-19: **P0 done.** `server/` uv project (FastAPI + ag-ui-protocol), stub text stream on :8090 via `npm run agui:py`; verified in the client Chat tab. Deviation: uvicorn ≥0.36 ignores the asyncio loop policy, so `run.py` uses a custom Selector loop factory (`app/loops.py`); gotcha 5 updated.
- 2026-09-19: **P1 done.** LangGraph router→responder (router fixed to `text`), streaming via `astream_events`, `AsyncPostgresSaver` on `a2ui_py`; verified in the client: name recall, recall after a Python server restart, New chat forgets. Startup log shows `checkpointer: postgres localhost:5432/a2ui_py` and `_WindowsSelectorEventLoop`. The bridge already ports the `status`/`a2ui`/`assistant_text` custom-event cases for P3.
- 2026-09-19: **P2 done.** `uv run pytest`: 34 green. Prompt byte-identical to Node (147,021 chars; template text extracted verbatim from `src/systemPrompt.js`), `graph_check` identical to Node on 14 fixtures (`scripts/dump-parity-fixtures.mjs`; `fixtures/.gitattributes` keeps them byte-exact), gate passes all 7 ported Node cases plus strictness cases. Deliberate differences: undeclared props rejected (intended); `unevaluatedProperties` cascade rewritten (see gotcha 2); non-bindable props like `Button.disabled` (plain `boolean`) now reject `{path}` bindings, which Node's binding hack let through; issue text is jsonschema's wording, not Zod's.
- 2026-09-19: **P3 done.** Real router + `ui_generator` (status → a2ui → caption, apology on gate failure), JSON-mode generator with repair loop; 54 pytest green. Verified in the client: text turn streams, sign-up form renders, a second UI in the same chat renders as a new surface with the first intact, and a real rejected→repaired run (`Button.disabled` bound to `/form/invalid` rejected as not `boolean`, valid on attempt 2/3). Reliable repro prompt: *"show me a newsletter sign-up card with an email field and a Subscribe button whose disabled state is bound to the data model at /form/invalid (seed it true)"*. Deliberate differences: router model follows Node's chain (`ROUTER_MODEL` → `OPENAI_MODEL` → `gpt-4o-mini`; with no `ROUTER_MODEL` set it runs on `gpt-5-mini`, ~2 s/turn); `A2UI_MAX_REPAIRS=0` means zero retries (Node's `|| 2` turned 0 into 2); graph nodes log router decisions and attempt counts into the request trace (Node's graph didn't pass its logger).
- 2026-09-19: **P4 done.** D1 resolved: `/generate` + `/health` ported into FastAPI on the gated generator, Vite proxy → :8090. Parity walkthrough in the client (text, memory incl. restart, form, list, modal, rejected→repaired, Generate UI tab) all good; the user noted UI latency (~20–35 s) → follow-up **F1**. Node backend deleted (`agent/`, `agui/`, `src/`, `test/*.mjs`, fixture script, Node-only deps); `npm run agui` = Python, `npm test` = pytest (60 green); prompt test is now a snapshot (`UPDATE_SNAPSHOTS=1`). README rewritten, architecture doc marked superseded. Verified in the client with no Node process: Chat and Generate UI tabs both work. Deliberate differences: `/generate` is validated + repaired (Node's was one-shot, non-blocking) and returns 422 with the errors as `hint` on failure; the Generate UI error text now says :8090.
- 2026-09-19: **F1 step 1 done.** Server-only progress: "Reading your request…" during DECIDE, then stage + ticking elapsed seconds during generation ("Fixing N issues… (attempt k of n)"); `status` may now repeat (contract note added). Verified in the client.
- 2026-09-19: **P5 done.** Templates `plan-tiles@1` (ComposableTileContainer tiles in a Row list template, nested feature list, Choose button with a `select_plan` event) and `plan-addons@1` (Checkbox checklist, `confirm_addons` event), hand-written from PDS components (no Figma frames yet; they're content, swappable later). Illustrative mock data in `data/`; providers `plans.list` (maxPrice, unlimitedOnly) and `addons.list` (planId) with declared field schemas; `FileTemplateStore`; DECIDE (strict structured output, `ROUTER_MODEL`) → POLICY (`config/personas.json`) → TEMPLATE / GENERATE / TEXT; `meta.source` + `meta.decision` on every surface; persona from `state.persona` (default assistant). 97 pytest green; 6/6 decision evals pass with `uv run pytest -m eval` (after narrowing TEXT to conceptual questions: "which plan fits" first came back TEXT). Verified in the client: plans tiles (identical layout across runs), "unlimited plans under $60" → same template with only Unlimited Go, travel question → GENERATE with gaps logged, 5G vs LTE → TEXT, add-ons for Unlimited Plus → plan-addons. **Known limitations:** GENERATE isn't given provider data yet, so generated plan UIs can invent plans/prices (P7 grounding); DECIDE on `gpt-5-mini` takes 3.5–17 s per turn, so set `ROUTER_MODEL=gpt-4o-mini`; ADAPT/REFINE fall back to GENERATE until P8.
- 2026-09-19: **P6 done.** Client (first intentional change, `Chat.tsx`): A2UI `event` actions POST back on the same thread as `forwardedProps.a2uiAction` (the A2UI v0.9 client-to-server message), shown as a dashed "You · UI action" bubble. Server: action → `[UI action] …` history turn + scalar context merged into persisted `selections`; manifests declare the `events` they emit, so DECIDE learns the source screen and gets its `suggestedNext` as hints (not a state machine); POLICY fills provider params DECIDE omitted from `selections` (planId comes from the click, never the model); a screen with no `suggestedNext` ends its flow with a TEXT summary. 105 pytest green; 10/10 decision evals (4 new action rows; the prompt got an explicit end-of-flow line after `confirm_addons` first came back GENERATE). Verified in the client: plans → Choose → that plan's add-ons → Continue → text summary; "the add-ons for my plan" reuses the chosen plan.
- 2026-09-19: **P7 done.** GROUND step before GENERATE: `guidelines.search` (local markdown in `guidelines/`: 5 hard rules DS-101..105, 9 soft DS-2xx, 3 patterns PAT-3xx; RAG behind `RagSource`, bypassed while `RAG_URL` is unset, D2), the catalog MCP server (`D:/DesignSystem/pds/mcp/catalog-server.mjs`, spawned via `MCP_SERVER_SCRIPT` with the gate's catalog, queried with the retrieved pattern's composition, D3), real provider data (DECIDE now returns `dataProviders`), then a structured design brief with cited rules; the generator builds from brief + data. VERIFY = schema gate + hard-rule lints (`app/verify/lints.py`, one per DS-1xx, test-enforced) + soft-rule LLM judge (`GUIDELINE_JUDGE`), all feeding the repair loop with rule id + text. Trace: `STEP_*` + `TOOL_CALL_*` events (`app/graph/trace.py`) and a client trace panel (`client/src/TracePanel.tsx`). Also: `OPENAI_REASONING_EFFORT` (default low) for gpt-5/o-series; an empty/truncated model reply is now a retried attempt, not a crash. 122 pytest green, 10/10 decision evals. Verified in the client: trace shows decision + reason, guideline sources, MCP components, provider data, brief, attempts and checks; the gate catches rule breaks. **Open:** F2 (slow ~80–110 s, layouts drift from the brief); D2 and D5 still placeholders.
- 2026-09-19: **P8 done.** Confirmed by the user in the client, and the walkthrough was re-run against the live backend: baseline plan-tiles@1 → cap red on Unlimited Go only (Variant 1, row split) → coverage ADAPT gives the baseline plus 3 variants, each listing the missing `coverage.*` data → "on variant 2…" gives Variant 2 · rev 2 with the others unchanged → the assistant's generated sign-up form, then REFINE renames the button. **Rough edges seen (not blockers):** (1) the judge flagged PAT-301 ("five tiles, should be 2–3") on the cap-colour variant: the split rewrites `plan-row`, so a finding the base screen already has looks new (F4 territory); (2) "on variant 2, make the badge say Recommended" changed only the 2nd plan's badge, reading "2" as the item as well as the variant; (3) the caption's "Unchanged:" list repeats "Baseline · plan-tiles@1" because ADAPT re-emits the baseline as a second record with the same label.
- 2026-09-19: **F5 done, verified in the client.** Declared data providers (`app/data/declared.py`, `data/providers/*.json`) load next to code providers in one live registry; fields derived from the data; param cases derived for the tests. Non-plan use case `order-history` added with no Python (data, declaration, template, 6 DECIDE rows). A generic DECIDE coverage rule fixed a regression the second domain caused on the travel row. 198 pytest green; evals 35/35.
- 2026-09-25: **D2 closed: the design-system RAG is wired into the flow.** `RagSource` now speaks the real contract (`POST http://127.0.0.1:5000/query {query, collection_name}` → `{answer, citations}`, `RAG_URL`/`RAG_COLLECTION`/`RAG_TIMEOUT`; `RAG_URL` is set in `.env`, so it is live). The service's `answer` is a citable source of its own (id `RAG-ANSWER`, as `GENUI-PORTING-PLAN.md` S5 names it), its citations become `RAG-<n>` sources (a cited rule keeps its `DS-1xx` id and merges with the local markdown, local text winning), so both reach the design brief, the ADAPT/REFINE prompts, the cards and the trace panel with no new prompt path. **Change requests ground through it:** REFINE/ADAPT query it with `<DECIDE's intent>. <the user's words>` — which needed a fix, `Plan.as_meta()` never carried `intent`, so `GROUND` had been querying with the raw message only. `guidelines.search` now traces which sources it asked (`args.in` shows the RAG URL + collection) so a bypassed, failing or answering endpoint is visible in the client. A failing call stays a note, never a broken turn. 205 pytest green (8 new: request shape, citation shapes, the `answers` list form, empty/odd responses, 404 degradation, local-wins-on-id, and two end-to-end change turns). **Not yet verified against the live service** — check `RAG_COLLECTION` matches a real collection.
