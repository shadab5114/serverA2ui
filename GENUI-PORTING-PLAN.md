# GenUI Backend on @vds/core: Implementation Plan

Build a generative-UI backend that answers chat messages with **text** or with **A2UI v0.9 surfaces** made from
the **@vds/core** design system. The surfaces are either curated templates filled with real data, or new UI
composed from the catalog and grounded in design guidelines. A React client renders them with real VDS
components. The implementation is ported from a working reference repository (the GenUI playground), with the
changes listed in *What changes and why*.

> **How to use this document.** Read it once end to end. Then work through the phases (**S1–S8**) in order.
> A phase is done only when its **Done when** can be seen in the React client (see *How to verify*).
> When a phase is done, tick it in **Status** and add one line to **Implementation log** at the bottom.
> Where this document and the reference code disagree, this document wins.

---

## Before you start: what to copy

Copy these from the reference repository into the office project (keeping the same relative paths), together
with this document:

| Copy | Why |
|---|---|
| `server/` — **without** `.venv/`, `__pycache__/`, `.pytest_cache/` and `server/.env` | The whole backend: graph, prompts, gate, templates and providers code, tests and evals. |
| `templates/` (3 folders) and `data/` (including `data/providers/`) | Working reference content: two flows and a declared provider. Rebuilt in VDS components in S1, replaced by office use cases in S7 and removed in S8. |
| `client/src/Chat.tsx`, `TracePanel.tsx`, `VariantCard.tsx` | Copied as they are. |
| `client/src/pdsCatalog.tsx` | The template for `vdsCatalog.tsx`. Not used as is. |
| `client/src/App.tsx`, `App.css`, `main.tsx`, `types.d.ts`, `client/vite.config.ts` | References for the tab, the styles, the CSS imports and the proxy. Merge into the existing client rather than overwriting it. |
| The root `package.json` scripts `agui` and `test` | How the backend and tests are run everywhere in this document. |

**Never copy** `server/.env` or the root `.env` (secrets), `.venv/`, `node_modules/`, or the reference
`guidelines/` folder (the RAG replaces it).

**Before the first phase, have these ready:** the `@vds/core` package (and registry credentials if it's
private), the Anthropic base URL, key and the model ids that endpoint serves, the Aurora connection details and
a database the app may create tables in, the MCP server URL (plus any auth header), and the RAG URL, its
collection name for design guidelines, and one real request and response so the adapter's field names are
right. Put them in `.env` as described in *Configuration*.

---

## Status

- [ ] **S1** Bring the code over; switch the design system to @vds/core
- [ ] **S2** Switch the LLM to the enterprise Anthropic endpoint
- [ ] **S3** Client: AG-UI chat, trace panel, variant cards, persona switch
- [ ] **S4** Durable memory on AWS Aurora PostgreSQL
- [ ] **S5** Grounding: hosted MCP server and RAG guidelines
- [ ] **S6** Tests and evals re-baselined on VDS and Claude
- [ ] **S7** First office use case, added without Python
- [ ] **S8** Cut-over: retire the Express backend, full walkthrough

---

## What you're building

**The client** has two screens. The **Chat** screen streams AG-UI events and renders surfaces inline. The
**Generate UI** screen is a single request to `POST /generate` that returns one surface.

**The backend** is Python: FastAPI, LangGraph and AG-UI over SSE. For each turn it runs one pipeline:

```
prompt (or a UI action) + persona + what's on screen
   │
   ▼
DECIDE    one structured-output call: {intent, strategy, templateId, params, coverage, gaps, dataProviders, target, reason}
   ▼
POLICY    plain code: is that strategy allowed for this persona and possible right now? If not, fall back
   ▼
GROUND    (GENERATE, ADAPT, REFINE) guidelines from RAG + components from the MCP server + real provider data
   ▼          → for GENERATE, a structured design brief with cited rules
BUILD     TEMPLATE: curated surface + provider data · GENERATE: new A2UI from the brief
   │      ADAPT: N variants as JSON Patches on a template · REFINE: the model returns only the changes to a surface on screen
   ▼
VERIFY    graph check → schema gate (catalog.json) → hard-rule lints → data contract → soft-rule judge
   │      failures go back to the model with the exact errors (repair loop)
   ▼
RESPOND   surface(s) + caption + trace (decision, sources, checks)
```

**Five strategies:**

| Strategy | What the backend does |
|---|---|
| `TEXT` | Streams a prose answer. For conceptual questions and conversation. |
| `TEMPLATE` | Shows a curated template filled with data from its provider. Provider params narrow the data. |
| `ADAPT` | Starts from a curated template and proposes N design variants as patches (explorer only). |
| `GENERATE` | Composes new UI from the catalog, grounded in guidelines and real data. |
| `REFINE` | Changes one surface already on screen ("make the button say Join now"). |

**Two personas**, one graph. The persona is a policy declared in `server/config/personas.json`:
- `assistant` may use TEXT, TEMPLATE, GENERATE and REFINE. It shows one surface per turn and repairs guideline
  conflicts before showing anything.
- `explorer` (for designers) may also use ADAPT. It gets 3 variants, and guideline conflicts are **flagged on
  the variant's card** instead of repaired. Every surface comes with rationale, sources and a list of changes.

**Data never comes from the LLM.** Names, prices, statuses and other values come from **data providers**. The
LLM picks templates, provider params, patches and compositions, never values. When a request needs data that no
provider has, the agent says so ("this variant needs a `coverage` field") instead of inventing it.

**Curated templates are content, not code.** Each is a folder `templates/<id>/` with `surface.json` (A2UI with
data bindings) and `manifest.json` (intent, examples, personas, provider). **Providers are data too:** a JSON
declaration in `data/providers/<name>.json` names a mock data file and says how each param filters. A new use
case needs **no Python**. See *Adding a use case*.

---

## What changes and why

The code is copied from the reference repository and then adapted. These are the only differences:

| # | Area | Reference | Office | Why | Where (phase) |
|---|---|---|---|---|---|
| 1 | Design system | `@shadab5114/pds-core` | **`@vds/core`** | The office design system. Its `catalog.json` drives the prompt, the validator gate and the client renderer. | Server catalog path, generator prompt examples, `COMMON_COMPONENTS`, client catalog adapter, reference templates, tests (**S1**, **S3**) |
| 2 | LLM | OpenAI (JSON mode, `gpt-5-mini`) | **Enterprise Anthropic endpoint** (`ANTHROPIC_BASE_URL` + `ANTHROPIC_API_KEY`) | Office LLM access. Claude needs no JSON mode: the prompt asks for JSON and the gate and repair loop enforce it. Small calls use native structured output. | `app/generation/llm.py`, `chat_model()` call sites, the text responder (**S2**) |
| 3 | Chat memory | Postgres in Docker | **AWS Aurora PostgreSQL** | No Docker in the office. Aurora is Postgres-compatible, so the LangGraph Postgres checkpointer works unchanged over TLS. A connection pool survives Aurora failovers and idle disconnects. | `app/state/checkpointer.py`, `DATABASE_URL` (**S4**) |
| 4 | MCP server | Spawned locally from a script | **Hosted MCP server** (same three tools) | The office hosts it, so the backend only connects and never starts a process. | `app/grounding/mcp.py`, `MCP_URL`, `MCP_HEADERS` (**S5**) |
| 5 | Guidelines | Local markdown files | **RAG API** (a prompt and a collection name in, `answers` + `citations` out) | Guidelines are served by the office RAG. Hard rules become lints written in code, and this plan ships none of them until the design-system team names some. | `app/grounding/sources.py`, `app/verify/lints.py` (**S5**) |
| 6 | Client transport | Express backend, no AG-UI | **AG-UI chat over SSE** plus the existing `/generate` call | The chat, trace panel, variant cards and UI actions need the streaming AG-UI contract. `/generate` stays so the existing screen keeps working. | Client (**S3**), Vite proxy, then retire Express (**S8**) |

Everything else is copied **as is**: the graph, DECIDE and POLICY, templates and providers (including declared
providers), GROUND, VERIFY, ADAPT and REFINE, lineage, the UI action round trip, the AG-UI bridge, the trace
events and the tests. Don't redesign them while porting. If a port and a redesign change the same behavior, a
bug can't be pinned to either one.

---

## What @vds/core must provide

The backend and client rely on the package the same way they relied on pds-core. Check each item before S1:

| Needed | Used by | Contract |
|---|---|---|
| `@vds/core/catalog.json` | Server: prompt, validator gate, MCP server | A2UI catalog: `{ "catalogId": "<id>", "components": { "<Name>": <JSON Schema>, … }, "$defs": { … } }`. Every `$ref` is local (`#/$defs/...`). Dynamic props are typed with the A2UI wire types (`DynamicString`, `DynamicBoolean`, …) so `{ "path": … }` bindings validate. Each component declares `unevaluatedProperties: false`. `action`, `checks` and `weight` are declared in a shared `$defs` entry (e.g. `CatalogComponentCommon`) so interactivity validates. |
| React components, one export per catalog name | Client catalog adapter | `import * as VDS from "@vds/core"` gives `VDS.<Name>` for every name in `catalog.json`. |
| `@vds/core/schemas` | Client catalog adapter | A zod schema per component, exported as `<Name>Schema`. It's attached to the catalog entry as its contract. |
| `@vds/core/styles.css` and the token CSS | Client `main.tsx` | Component styles and design tokens (CSS custom properties). The tokens must load first. |

The layout components `Column`, `Row`, `List` and `Divider` are **not** expected in `@vds/core`. They come from
the basic A2UI catalog on both sides: `server/app/grounding/layout.py` and the client's `FALLBACK_LAYOUT`. If
VDS ships a component with one of those names, the VDS one wins on the client, and the server must validate it
from the VDS catalog. Remove that name from `layout.py`'s layout set so the two sides agree.

If the package lives in a private registry, add the registry and token to `.npmrc` at the repo root (the server
reads the catalog from the root `node_modules`) and in `client/`.

---

## The VDS component set is different, and that's fine

**Do not build a PDS→VDS component comparison.** The reference design system's component names have no
authority here. `@vds/core/catalog.json` is the only source of truth: the generator prompt, the validator gate
and the client all read it, so whatever it contains is what the system can build with. A mapping table would
only be a second, stale source of truth.

Component names appear in exactly these places, and nowhere else:

| Where | What to do |
|---|---|
| `client/src/vdsCatalog.tsx` — `componentMap` | Mechanical: one entry per name in `catalog.json` → the VDS React component of that name. |
| `client/src/vdsCatalog.tsx` — `CLOSE_ACTION`, `TWO_WAY` | Only the components that act on close (modal, notification) and the inputs. |
| `app/generation/prompt.py` — interactivity examples | Rewrite the two or three examples using VDS components that exist. |
| `app/explore/variants.py` — `COMMON_COMPONENTS` | Pick the VDS names for: body text, badge, inline notification, button, and an accordion with its item. |
| `templates/*/surface.json` | Re-author from VDS components (see below). |
| `tests/test_gate.py`, `tests/test_explore.py`, `tests/test_contract.py`, `evals/modify_cases.py` | Swap the components in fixture documents; keep every assertion. |

**Choose by role, not by name.** List what VDS offers and pick the closest fit:

```bash
node -e "const c=require('./node_modules/@vds/core/catalog.json');
const props=(s)=>Object.keys(((s.allOf||[]).find(x=>x.properties)||s).properties||{});
for (const [n,s] of Object.entries(c.components)) {
  const p=props(s), role=['children','action','label','value','checked'].filter(k=>p.includes(k)).join(',');
  console.log(n.padEnd(26), (role||'-').padEnd(24), (s.description||'').slice(0,70)); }"
```

The roles the system needs are: a **container that takes `children`** (for tiles and cards that hold a body),
**text** at a few sizes, an **action** (a button with an `action` prop), **inputs** (a `value` or `checked`
prop plus a `label`), a short **status label** (badge or pill), and a **message** component (notification or
banner). Layout comes from `Column`, `Row`, `List` and `Divider`, which aren't part of VDS.

**Templates are content: rebuild the screen, don't translate it.** Keep the data bindings, list templates,
event names and the manifest exactly as they are, because the providers, tests and evals depend on them. Choose
VDS components freely for everything else. If VDS has no equivalent of something (say a tile has no badge
strip), **drop that detail or express it another way** — a badge component above the title works as well. A
simpler screen built from components that really exist is the goal; a faithful imitation of the reference is
not.

**Never invent a component or a prop.** If it isn't in `catalog.json`, the gate rejects it and the turn fails.
Two checks catch mistakes immediately, so lean on them instead of reasoning about the catalog for long:
`npm test` (every template gates with every param case, and fixtures are validated) and the startup banner's
component count.

## The client: what changes

Your client keeps everything it has. The Generate UI screen only changes where it points (S2). What's new is the
Chat screen and the catalog adapter. Full build steps are in **S3**; this is the shape of the work.

| File | Change | What it does |
|---|---|---|
| `src/vdsCatalog.tsx` | **Adapt** (from the reference `pdsCatalog.tsx`) | Builds the `@a2ui/react` catalog from `@vds/core`, so A2UI JSON renders as real VDS components. The one file that carries design-system knowledge. |
| `src/Chat.tsx` | **Copy** | The chat screen: sends a turn, parses the SSE stream, renders text and surfaces inline, posts UI actions back, holds the persona switch. |
| `src/TracePanel.tsx` | **Copy** | Folds `STEP_*` and `TOOL_CALL_*` events into a per-turn list: the decision, guideline and MCP queries with their sources, provider data, the brief, each attempt and each check. |
| `src/VariantCard.tsx` | **Copy** | The chrome around a surface when `meta.card` is present: label, rationale, sources, what changed, guideline flags, missing data, and the patch on demand. |
| `src/App.tsx` | **Edit** | Adds a Chat tab beside the existing Generate UI screen. |
| `src/main.tsx`, `src/types.d.ts` | **Edit** | Import the VDS token CSS first, then `@vds/core/styles.css`; declare those CSS modules for TypeScript. |
| `vite.config.ts` | **Edit** | Proxy `/agui`, `/generate` and `/health` to the backend; dedupe `react`/`react-dom`. |
| `package.json` | **Edit** | Add `@a2ui/react` and `@a2ui/web_core` (0.9.1), `zod` 4 and `@vds/core` with its token package. |

**The catalog adapter is the only real work.** It is "binderless": the generic A2UI binder inspects zod-v3
schema internals, and design-system schemas describe component props rather than the A2UI wire format, so the
adapter resolves values itself and hands plain props to the VDS component. What it must handle:

- `componentMap`: one entry per name in `@vds/core/catalog.json` → the VDS React component.
- `schemaMap`: `<Name>Schema` from `@vds/core/schemas`, attached to each catalog entry as its contract.
- Value shapes: `{path}` bindings, `{path, componentId}` list templates (render the component once per array
  item, resolving relative paths), static child lists, and action values (`event`, `functionCall`).
- Per-component tables to review against VDS: which components fire their action on close rather than click
  (modal, notification), and which are inputs, with the prop that holds the value, its default prop, and how to
  read the change event.
- The `setData` and `toggleData` functions the generated UI uses for local UI state, merged onto the basic
  catalog's functions.
- The layout fallback (`Column`, `Row`, `List`, `Divider`) from the basic A2UI catalog, with VDS winning on any
  name clash.
- `CATALOG_NAME` (e.g. `"vds"`), the id surfaces are registered under.

If your client already renders A2UI with a VDS adapter, keep it — just confirm it covers every point above,
especially list templates, two-way inputs and actions, which the chat depends on.

**What the chat screen does, so you can judge how it fits your client:** it keeps one `threadId` per
conversation and sends only the newest user message (the backend restores the rest from memory); it parses SSE
frames itself with `fetch` (no AG-UI client library); it appends `TEXT_MESSAGE_CONTENT` deltas to the current
assistant bubble, shows the latest `status` text while a UI is being built, and feeds `CUSTOM a2ui` messages to
a `MessageProcessor` that renders surfaces inline in that turn; the processor's action sink posts A2UI `event`
actions back on the same thread and shows them as a compact "UI action" bubble; "New chat" rotates the
`threadId` and tears down rendered surfaces.

**Two things to keep exactly as they are:** the client rewrites every `surfaceId` to a fresh id per turn (the
backend always names its surface `"main"`, so without this each new surface would overwrite the earlier ones)
and sets `catalogId` to the registered catalog name. Both happen in `normalizeA2ui`.

**Backend errors to surface:** `RUN_ERROR` carries a message to show, and a failed `fetch` should say the
backend may not be running.

## How to verify

**Acceptance happens in the React client, never with curl.** Run the backend (`npm run agui`) and the client
(`cd client && npm run dev`), type the prompt, and look at the result. pytest and the evals are development aids
and the safety net. A phase isn't done until the client shows it working.

**Side-by-side:** run a second backend instance on another port (`uv run python run.py --port 8091`) and start
the client with `AGUI_TARGET=http://localhost:8091` (bash) or `$env:AGUI_TARGET="http://localhost:8091"`
(PowerShell). Set `API_TARGET` the same way for `/generate` and `/health`.

---

## The wire contract

The client depends on exactly this.

### `POST /agui/run` (Chat screen)

**Request**, `Content-Type: application/json`:

```json
{ "threadId": "thread_<uuid>", "runId": "run_<ms>",
  "messages": [{ "id": "u_<ms>", "role": "user", "content": "<text>" }],
  "state": { "persona": "assistant" } }
```

- Use only the **newest `role: "user"` message**. Earlier turns come from the checkpointer, keyed by `threadId`.
- Missing `threadId` or `runId` → generate `thread_<uuid4>` / `run_<uuid4>`.
- `state.persona` is `"assistant"` or `"explorer"`. Missing or unknown means `assistant`.
- **A UI action** (a component's A2UI `event`, e.g. a Choose button) is sent on the same `threadId` with
  `messages: []`:
  `{ "threadId", "runId", "messages": [], "state": {…}, "forwardedProps": { "a2uiAction": { "version": "v0.9", "action": { "name", "surfaceId", "sourceComponentId", "timestamp", "context" } } } }`.
  `context` arrives with bindings already resolved. The server records it as a `[UI action] <name> …` history
  turn and merges its scalar values into the thread's `selections`.
- **Parse leniently.** Don't bind the body to `ag_ui.core.RunAgentInput`: the client omits `tools`, `context`
  and sometimes `forwardedProps`, and a strict model returns 422.

**Response:** status 200 with `Content-Type: text/event-stream`, `Cache-Control: no-cache, no-transform`,
`Connection: keep-alive` and `X-Accel-Buffering: no`. Each event is one SSE frame `data: <json>\n\n`: a single
`data:` line with no `event:` field. JSON keys are camelCase (serialize the ag_ui models by alias, excluding
`None`).

Text turn:
```
RUN_STARTED           { threadId, runId }
CUSTOM                { name: "status", value: { text: "Reading your request…" } }
TEXT_MESSAGE_START    { messageId, role: "assistant" }
TEXT_MESSAGE_CONTENT  { messageId, delta }            ← one per streamed chunk
TEXT_MESSAGE_END      { messageId }
RUN_FINISHED          { threadId, runId }
```

UI turn:
```
RUN_STARTED
CUSTOM                { name: "status", value: { text: "<stage> … 12s" } }     ← repeated, about once a second
CUSTOM                { name: "a2ui",   value: { a2ui: [ …A2UI messages ], meta: { … } } }   ← one per surface
TEXT_MESSAGE_START / TEXT_MESSAGE_CONTENT / TEXT_MESSAGE_END                  ← the caption
RUN_FINISHED
```

- An explorer ADAPT turn emits several `a2ui` events in one run: the baseline first, then each variant as soon as
  it passes verification.
- `meta.source` is `{kind: "template", id, version}`, `{kind: "variant", id, base, rev}` or
  `{kind: "generated", id, rev}`. `meta.decision` holds the plan after POLICY.
- `meta.card` (only for personas with `showRationale`) is what the variant card shows:
  `{id, kind, label, base, rev, title, rationale, sources[{id,title}], changes[], flags[], missingData[], patch}`.
- If no valid UI comes out of the repair loop, skip the `a2ui` event and send the text trio with an apology.
- **Errors:** on an exception, emit `RUN_ERROR { message }` (unless the client has disconnected), then close.
- **Client disconnect:** stop consuming the graph and don't emit `RUN_FINISHED`.

**Trace events** wrap the turn. They're additive: a client that ignores them still works.
- `STEP_STARTED` / `STEP_FINISHED { stepName }` for `decide`, `ground`, `build`, `baseline`, `variants`,
  `rebuild` and `refine`.
- Each traced call is `TOOL_CALL_START { toolCallId, toolCallName }` → `TOOL_CALL_ARGS { delta: <json args> }` →
  `TOOL_CALL_END` → `TOOL_CALL_RESULT { messageId, toolCallId, content: <json result with a "summary">, role: "tool" }`.
  Traced calls are the decision, `guidelines.search`, `mcp.resolve_intent_to_schema`, each data provider,
  `design_brief`, each `generate_a2ui` attempt, `guidelines.lint`, `guidelines.judge`, `propose_variants`,
  `variant.check`, `variant.repair` and `lineage.rebuild`.

**Fields the client reads:** `type`, `delta`, `name`, `value`, `value.text`, `value.a2ui`, `value.meta.card`,
`message`. Keep the rest for logs and the trace panel.

### `POST /generate` (Generate UI screen)

`{ "prompt": "<text>" }` → 200 `{ "meta": {…, "catalogId", "components", "generatedAt"}, "a2ui": [ … ] }`.
If no attempt passes the gate, it returns 422 `{ "error", "hint": "- <validator error>\n…" }`. A missing prompt
is 400. Exceptions are 500 `{ "error" }`. The result goes through the same generate → gate → repair loop as
chat. If the existing client calls the Express backend with a different request or response shape, change that
one client call to this contract; don't add a second shape to the server.

### Health

- `GET /agui/health` → `{ "status": "ok", "phase": <n>, "endpoint": "/agui/run", "checkpointer": "postgres" | "memory" }`
- `GET /health` → `{ "status": "ok", "provider": "anthropic", "catalogSource": "local" }`

### The A2UI envelope

```json
{ "a2ui": [
  { "version": "v0.9", "createSurface":    { "surfaceId": "main", "catalogId": "<catalog id>" } },
  { "version": "v0.9", "updateDataModel":  { "surfaceId": "main", "path": "/", "value": { } } },
  { "version": "v0.9", "updateComponents": { "surfaceId": "main", "components": [ { "id": "root", "component": "Column", "children": ["a"] } ] } }
] }
```

Each message has exactly one message key. The component list is flat, with exactly one `id: "root"`. Props are
inline, bindings are `{ "path": "/json/pointer" }`, and list templates are `children: { "path", "componentId" }`
with relative paths inside the repeated component. The server always names the surface `"main"`. **The client
rewrites `surfaceId` and `catalogId` on every turn** (`normalizeA2ui` in `Chat.tsx`) so surfaces don't collide.
Don't "fix" that on the server.

---

## Target layout

Files marked **✎** change during the port. Unmarked files are copied as they are.

```
templates/<id>/                 curated templates: surface.json + manifest.json (content)
data/                           mock data files (content)
data/providers/<name>.json      declared data providers (content)
server/
  pyproject.toml            ✎   uv project, Python ≥3.12; anthropic + langchain-anthropic replace langchain-openai
  .env.example              ✎   server-only settings (Aurora URL, MCP, RAG)
  run.py                        entry point: Selector event loop + uvicorn
  config/personas.json          persona policies
  app/
    main.py                 ✎   FastAPI app, lifespan (checkpointer, MCP, graph), routes, startup banner
    config.py               ✎   settings (see Configuration)
    log.py                      readable one-line flow log per request
    agui_bridge.py              graph events → AG-UI events (the wire contract)
    graph/
      playground.py         ✎   the graph: decide → template / generate / text / adapt / refine; the text responder
      explore.py                adapt and refine nodes
      state.py                  graph state (messages, selections, surfaces, last_surface)
      progress.py               repeated "status" events with elapsed seconds
      trace.py                  STEP_* and TOOL_CALL_* events
    decide/decide.py        ✎   DECIDE: structured decision (switch to chat_model(), no temperature)
    decide/policy.py            POLICY: allowed strategies, fallbacks, params from selections
    data/providers.py           code providers + the live provider registry
    data/declared.py            declared providers (JSON → Provider)
    templates/store.py          TemplateStore + FileTemplateStore (re-read on every call)
    templates/render.py         fill a template with provider data, gate it
    ground/ground.py        ✎   GROUND: guidelines + MCP + data → design brief (switch to chat_model())
    grounding/catalog.py    ✎   load @vds/core/catalog.json once
    grounding/layout.py         Column/Row/List/Divider schemas for the prompt
    grounding/mcp.py        ✎   hosted MCP client (resolve_intent_to_schema)
    grounding/sources.py    ✎   guideline sources: the RAG adapter
    generation/llm.py       ✎   Anthropic calls: A2UI generation (raw SDK, streamed, cached) + chat_model()
    generation/prompt.py    ✎   generator system prompt (catalog + rules + interactivity examples in VDS components)
    generation/graph_check.py   orphan and root repair
    generation/gate.py          jsonschema (Draft 2020-12) gate against catalog.json
    generation/generate.py      generate → graph check → gate → lints → judge → repair loop
    verify/lints.py         ✎   hard rules as code (starts empty)
    verify/judge.py         ✎   soft rules via an LLM judge (switch to chat_model())
    explore/variants.py     ✎   ADAPT variants (COMMON_COMPONENTS → VDS names)
    explore/modify.py           REFINE: the model returns only the changes
    explore/patching.py         JSON Patch over a {components: {id: …}} view
    explore/lineage.py          what's on screen, rebuilding a surface from its record
    state/checkpointer.py   ✎   Aurora: AsyncPostgresSaver over a connection pool
  evals/decisions.jsonl     ✎   decision evals (rows for the office use cases)
  evals/modify_cases.py     ✎   REFINE eval screens, re-expressed in VDS components
  tests/                    ✎   see Tests and evals
client/src/
  Chat.tsx                      AG-UI chat: SSE parse, persona switch, UI action post-back, normalizeA2ui
  TracePanel.tsx                decision, steps and tool calls per turn
  VariantCard.tsx               explorer card: label, rationale, sources, changes, flags, missing data
  vdsCatalog.tsx            ✎   @a2ui/react catalog built from @vds/core (ported from pdsCatalog.tsx)
  App.tsx                   ✎   Chat and Generate UI tabs
  main.tsx, types.d.ts      ✎   VDS CSS imports and module declarations
client/vite.config.ts       ✎   proxy /agui, /generate and /health to the new backend
```

Not copied: `guidelines/` (replaced by RAG), `docs/`, the design-system skills, and anything Node-backend
related.

---

## Configuration

Settings load from the **root `.env`** (shared keys) and then **`server/.env`** (overrides). Never print secret
values, and never commit either `.env`. Keep `.env.example` files with placeholders only.

| Key | Default | Used for |
|---|---|---|
| `ANTHROPIC_API_KEY` | (required) | Enterprise Anthropic key |
| `ANTHROPIC_BASE_URL` | (required) | Enterprise Anthropic-API-compatible base URL. Read by both the SDK and `ChatAnthropic`. |
| `ANTHROPIC_MODEL` | `claude-opus-5` | Main model: A2UI generation, ADAPT variants, REFINE changes |
| `ANTHROPIC_FAST_MODEL` | `claude-sonnet-5` | DECIDE, design brief, guideline judge and the text responder |
| `LLM_EFFORT` | `low` | `output_config.effort` for every call. Building JSON from a brief needs little deliberation, and it keeps turns fast. Raise it only if an eval shows a gain. |
| `LLM_MAX_TOKENS` | `32000` | Output cap for A2UI generation (streamed, so no HTTP timeout) |
| `A2UI_MAX_REPAIRS` | `2` | Repair attempts after a failed check (`0` = none) |
| `DATABASE_URL` | unset → in-memory | Aurora writer endpoint, e.g. `postgresql://USER:PASSWORD@<cluster>.cluster-<id>.<region>.rds.amazonaws.com:5432/<db>?sslmode=require`. URL-encode special characters in the password. |
| `DB_POOL_MAX` | `10` | Checkpointer connection pool size |
| `LOCAL_CATALOG_PATH` | `<repo>/node_modules/@vds/core/catalog.json` | Catalog source |
| `TEMPLATES_DIR` | `<repo>/templates` | Curated templates |
| `DATA_DIR` | `<repo>/data` | Mock data the providers read |
| `PROVIDERS_DIR` | `DATA_DIR/providers` | Declared providers |
| `MCP_URL` | (required for S5) | Hosted MCP server, Streamable HTTP |
| `MCP_HEADERS` | unset | JSON object of HTTP headers for the MCP server, e.g. `{"Authorization": "Bearer …"}` |
| `RAG_URL` | (required for S5) | RAG endpoint |
| `RAG_COLLECTION` | (required for S5) | Collection that holds the design guidelines |
| `RAG_TIMEOUT` | `30` | Seconds. RAG writes an answer, so it's slower than plain search. |
| `GUIDELINE_JUDGE` | `on` | The soft-rule judge (one extra fast-model call per verified surface) |
| `AGUI_PORT` | `8090` | Server port (`run.py --port` overrides) |

Removed from the reference: `OPENAI_*`, `ROUTER_MODEL`, `LLM_PROVIDER`, `OPENAI_REASONING_EFFORT`,
`MCP_SERVER_SCRIPT` and `GUIDELINES_DIR`. Replace every `settings.router_model` use with the fast model through
`chat_model()`.

**Model IDs:** use exactly the IDs your enterprise endpoint serves. The defaults are the current Claude
models (`claude-opus-5`, `claude-sonnet-5`). If the endpoint names them differently, change only the two env
values. Then re-run the evals (S6), because DECIDE and the judge are sensitive to the model.

---

## Phases

### S1: Bring the code over; switch the design system to @vds/core

**Build**
- Copy from the reference repo: `server/` (without `.venv/`, `__pycache__/`, `.pytest_cache/` and `server/.env`),
  `templates/` and `data/` (reference content), and the root `package.json` scripts `agui`
  (`cd server && uv run python run.py`) and `test` (`cd server && uv run pytest`). Add `.venv/`, `__pycache__/`
  and `.pytest_cache/` to `.gitignore`.
- Python 3.12 and uv. `cd server && uv sync`.
- `npm install @vds/core` at the repo root (the server reads `node_modules/@vds/core/catalog.json`).
- **Catalog:** in `app/config.py`, default `LOCAL_CATALOG_PATH` to `node_modules/@vds/core/catalog.json`. In
  `app/grounding/catalog.py`, change the "is the package installed?" error text to name `@vds/core`. The loader
  itself doesn't change: `{catalogId, components, defs, names}`. In `app/main.py`, change the banner's
  "pds components" wording.
- **Generator prompt** (`app/generation/prompt.py`): it's built from the catalog, so the component schemas follow
  automatically. The hand-written parts name components and must use VDS names and props: the
  **interactivity examples** (a form with an input, a checkbox and a submit button; a button opening a modal;
  validation `checks`) and any prop names in the rules. Rewrite each example with the VDS equivalent. Keep the
  structure, the output contract ("Return ONLY this JSON object — no markdown, no prose, no code fences"), the
  binding and list-template rules, and the `setData`/`toggleData` function examples. Then refresh the prompt
  snapshot: `UPDATE_SNAPSHOTS=1 npm test` (bash), and read the diff once to confirm only intended text changed.
- **`COMMON_COMPONENTS`** in `app/explore/variants.py`: the components always offered to ADAPT and REFINE besides
  the ones on screen. Set it to the VDS equivalents of: body text, badge, inline notification, button, the four
  layout components, and an accordion with its item. Every name must exist in the VDS catalog or in `layout.py`.
- **Neutral examples** in the ADAPT and REFINE prompts (`variants.py`, `modify.py`) use `"component": "Text"`.
  If VDS names its text component differently, rename it there too.
- **Reference templates:** re-author `plan-tiles`, `plan-addons` and `order-history` in VDS components, as
  described in *The VDS component set is different, and that's fine*. Keep
  every binding path, list template, `event` name and the manifests as they are, because the providers and
  evals depend on them. Pick VDS components that can hold the content (a tile with a body for plan and order
  tiles, a checkbox list for add-ons). They're working examples for S3–S6; office use cases replace them in S7.
- **Tests that build PDS documents** must use VDS components: `tests/test_gate.py` (component validation
  cases), `tests/test_explore.py` and `tests/test_contract.py` fixtures, and `evals/modify_cases.py`. Keep what
  each test asserts; only the component names and props change.
- **Hard-rule lints:** empty the lint registry in `app/verify/lints.py` and delete the placeholder DS-10x
  checks, which were the reference project's rules, not VDS's. Keep the mechanism (see S5).

**Done when:** `npm test` passes except the LLM-dependent tests you haven't ported yet. They're fixed in S2. The
server starts (`npm run agui`), and the banner shows `catalog: <N> … components (<VDS catalogId>)` and the three
templates. At this point the LLM calls still need S2.

### S2: Switch the LLM to the enterprise Anthropic endpoint

**Build**
- Dependencies: `cd server && uv remove langchain-openai openai` (if present), then `uv add anthropic langchain-anthropic`.
  (`anthropic` 1.x uses `httpx2` internally. The app's own `httpx` use in RAG and the MCP probe is separate and
  unaffected.)
- **`app/generation/llm.py`: A2UI generation through the raw SDK.** Keep `parse_json` (direct parse, then a
  fenced block, then the first `{` to the last `}`). Remove the OpenAI path and the reasoning-model helpers.
  The call:
  ```python
  from anthropic import AsyncAnthropic

  _client: AsyncAnthropic | None = None

  def client() -> AsyncAnthropic:
      global _client
      if _client is None:
          _client = AsyncAnthropic(api_key=settings.anthropic_api_key, base_url=settings.anthropic_base_url)
      return _client

  async def generate_a2ui(system_prompt: str, user_prompt: str) -> Generation:
      async with client().beta.messages.stream(
          model=settings.anthropic_model,
          max_tokens=settings.llm_max_tokens,
          # The system prompt is large and static (the whole catalog), so cache it: turns after the first
          # read it at a fraction of the cost and latency.
          system=[{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}],
          messages=[{"role": "user", "content": user_prompt}],
          output_config={"effort": settings.llm_effort},
          betas=["server-side-fallback-2026-07-01"],
          fallbacks="default",  # a safety-classifier decline is re-run on Anthropic's recommended fallback model
      ) as stream:
          message = await stream.get_final_message()
      if message.stop_reason == "refusal":
          raise ValueError("The model declined this request.")
      if message.stop_reason == "max_tokens":
          raise ValueError(f"The model ran out of output tokens (LLM_MAX_TOKENS={settings.llm_max_tokens}).")
      text = "".join(b.text for b in message.content if b.type == "text")
      return {"json": parse_json(text), "provider": "anthropic", "model": message.model,
              "cacheRead": message.usage.cache_read_input_tokens or 0}
  ```
  A `ValueError` here is an unusable reply, which the repair loop counts as a failed attempt, not a crash (keep
  that test). Don't use assistant prefill to force JSON: current Claude models reject it with a 400. The
  prompt's output contract, `parse_json` and the gate do that job.
- **`chat_model()`** (same file) returns the LangChain chat model for the small calls:
  ```python
  from langchain_anthropic import ChatAnthropic

  def chat_model(**kwargs) -> ChatAnthropic:
      return ChatAnthropic(model=settings.anthropic_fast_model, api_key=settings.anthropic_api_key,
                           base_url=settings.anthropic_base_url, max_tokens=8192,
                           output_config={"effort": settings.llm_effort}, **kwargs)
  ```
  **No `temperature` anywhere.** Current Claude models reject sampling parameters. Update the three structured
  callers: `make_decide_model()` in `decide/decide.py`, `make_brief_fn()` in `ground/ground.py` and
  `make_judge()` in `verify/judge.py`. Each becomes `chat_model().with_structured_output(<Model>, method="json_schema")`
  (native structured output, so drop `strict=True`). The Pydantic models (`Decision`, `DesignBrief`, `Verdict`)
  don't change.
- **Text responder** (`graph/playground.py`): replace `ChatOpenAI(model=…, temperature=1, streaming=True)` with
  `chat_model(streaming=True)`. The bridge already turns only the responder node's `text` parts into
  `TEXT_MESSAGE_CONTENT`. Claude's thinking parts are ignored.
- **Point the existing client's generate call at the new backend:** set the Vite proxy (or the client's API base
  URL) for `/generate` and `/health` to `http://localhost:8090`.
- Log `cacheRead` in the generation trace so you can see caching working.
- `app/main.py`: the startup banner prints the main and fast model ids (instead of the OpenAI and router
  models), and `GET /health` returns `"provider": "anthropic"`.

**Done when:** in the existing client, a generate request ("a sign-up form with email, password and a submit
button") renders a VDS surface produced by the new backend. The server log shows the attempt count, and from
the second request on the trace shows `cacheRead > 0`. `npm test` is fully green.

### S3: Client: AG-UI chat, trace panel, variant cards, persona switch

**Build**
- Dependencies in `client/`: `@a2ui/react` and `@a2ui/web_core` 0.9.1, `zod` 4, React 19 and `@vds/core` (plus
  its token CSS package). The chat uses plain `fetch` plus an SSE parser, so no AG-UI client library is needed.
- **Catalog adapter** `client/src/vdsCatalog.tsx`, ported from the reference `pdsCatalog.tsx`. Everything it
  must cover is listed in *The client: what changes*; the per-component tables to review against VDS are
  `CLOSE_ACTION` (action fires on close) and `TWO_WAY` (inputs), plus `CATALOG_NAME`.
- Copy `Chat.tsx`, `TracePanel.tsx` and `VariantCard.tsx`. Point their imports at `vdsCatalog`.
- `App.tsx`: a **Chat** tab and the existing **Generate UI** tab. `main.tsx`: import the VDS token CSS first,
  then `@vds/core/styles.css`. `types.d.ts`: declare the CSS modules.
- `vite.config.ts`: proxy `/agui` (`AGUI_TARGET`), `/generate` and `/health` (`API_TARGET`) to the new backend
  (default `http://localhost:8090`), and dedupe `react`/`react-dom`.

**Done when**, in the client's Chat tab, with the in-memory checkpointer:
- "what is a design system?" streams text.
- "show me the plans" renders the curated plan tiles. The layout is identical across runs, and the trace panel
  shows `decide` with `TEMPLATE plan-tiles` and its reason.
- Clicking **Choose** on a plan shows a dashed "UI action" bubble, then that plan's add-ons.
- "show me a sign-up form with email, password and a submit button" renders a generated surface, and "make the
  button say Join now" changes only that button (REFINE).
- Switching to **Explorer** and asking "show me plan details" shows a "Baseline · plan-tiles@1" card.

### S4: Durable memory on AWS Aurora PostgreSQL

**Build**
- Get from the DBA a database for this app (e.g. `a2ui`) and a user allowed to create tables in it. On first
  start the app creates its checkpoint tables (`setup()`). Use the cluster's **writer** endpoint.
- `DATABASE_URL` in `server/.env` with `?sslmode=require` (TLS is mandatory on Aurora). If your policy requires
  certificate verification, use `sslmode=verify-full&sslrootcert=<path to the AWS RDS CA bundle>`.
- `app/state/checkpointer.py`: open a pool instead of a single connection, so a failover or an idle disconnect
  costs one retry, not a dead backend:
  ```python
  from psycopg.rows import dict_row
  from psycopg_pool import AsyncConnectionPool
  from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

  async with AsyncConnectionPool(
      conninfo=database_url, max_size=settings.db_pool_max, open=False,
      kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
      check=AsyncConnectionPool.check_connection,  # test a connection before handing it out
  ) as pool:
      saver = AsyncPostgresSaver(pool)
      await saver.setup()
      yield Checkpointer(saver, "postgres", _describe(database_url))
  ```
  `_describe` prints host and database only, never credentials. No `DATABASE_URL` still means in-memory.
- On Windows, psycopg's async mode needs the Selector event loop. `run.py` already passes
  `loop="app.loops:selector_loop_factory"` to uvicorn. Keep it.

**Done when:** the banner shows `checkpointer: postgres <aurora host>:5432/<db>`. In the client you tell the
chat your name, restart the backend, ask for your name on the same chat, and it remembers. "New chat" forgets.

### S5: Grounding: hosted MCP server and RAG guidelines

**Build: MCP** (`app/grounding/mcp.py`)
- Connect only; remove `_spawn`, `MCP_SERVER_SCRIPT` and the process handling. At startup, connect with
  `MultiServerMCPClient({"vds-catalog": {"transport": "streamable_http", "url": settings.mcp_url, "headers": settings.mcp_headers}})`
  and load the tools. The backend uses `resolve_intent_to_schema` (`{intent, limit}` → `{matched: [{name}], components: {name: schema}}`).
  `list_component_catalog` and `get_component_schema` are listed in the banner.
- The hosted server must serve the **same `@vds/core` catalog version** the gate validates against. Otherwise
  it suggests components the gate rejects.
- An unavailable MCP never breaks a turn: calls return `{answer: "", sources: [], note}` and the note shows in
  the trace. Keep the reachability probe short (1.5 s) so a down server doesn't stall startup.

**Build: RAG** (`app/grounding/sources.py`)
- `Guidelines` has one source: `RagSource`. Delete `LocalGuidelines` and the markdown parsing.
- Give `Source` an explicit `kind` field (`"hard"`, `"soft"`, `"pattern"`) instead of deriving it from id
  prefixes, and update the two filters that select soft rules for the judge (`Grounding.soft_rules` in
  `ground/ground.py` and `_soft()` in `graph/explore.py`) to read the field.
- `RagSource.search(query)`:
  ```python
  resp = await client.post(settings.rag_url, json={"prompt": query, "collection_name": settings.rag_collection},
                           timeout=settings.rag_timeout)
  resp.raise_for_status()
  return self._parse(resp.json())
  ```
  `_parse(body)` turns `{"answers": …, "citations": [...]}` into a `GroundingResult`:
  - `answers` (a string, or a list of strings joined with blank lines) becomes the result's `answer` **and** a
    source `Source(id="RAG-ANSWER", title="Guidance for this request", text=<answers>, origin="rag", kind="soft")`,
    so the design brief and the judge see the guidance even when citations carry no text.
  - Each citation (a string, or an object) becomes `Source(id=<citation id, else "rag-<n>">, title=<title or
    source name>, text=<text/content/snippet, else "">, origin=<url or document, else "rag">, kind=<its type if
    it is hard/soft/pattern, else "soft">)`.
  - Use the exact request and response field names of the office RAG API. They live only in `search` and
    `_parse`.
- A failed RAG call never breaks a turn: `Guidelines.search` records `guidelines.rag: failed (…)` as a note, and
  the brief is built without guidelines.
- **Hard rules** (`app/verify/lints.py`): each hard rule is one entry `{id, title, text, check}`, where `check`
  is a deterministic function over the surface returning violations. The rule text lives next to its check, and
  violations go to the repair loop quoting it. The registry starts **empty**. Add a rule only when the
  design-system team names a hard rule. Its test is a surface that breaks it and one that doesn't.

**Done when**, in the client: "which plan fits someone who travels a lot?" produces a **generated** surface, and
the trace panel shows `guidelines.search` with RAG citations, `mcp.resolve_intent_to_schema` with VDS
components, the provider data, the `design_brief` citing guideline ids, the attempts, and `guidelines.judge`.

### S6: Tests and evals re-baselined on VDS and Claude

**Build**
- `npm test` fully green (see *Tests and evals* for what each suite guards).
- Run the real-model evals: `cd server && uv run pytest -m eval` (the decision evals plus
  `tests/test_modify_eval.py`). They call the enterprise endpoint, so they cost money: run them on demand, not
  in the default suite.
- For every failing row, find out whether the decision or the expectation is wrong. Fix prompts **generically**:
  state the principle, never a domain example. Prompts and engine code must not mention the office's domains.
  Rerun until the whole set passes twice in a row. Record the timings of a template turn, a generated turn and a
  REFINE turn from the trace (TOOL_CALL_START/RESULT timestamps).

**Done when:** `npm test` is green, the decision evals pass twice in a row, and the modify eval passes every
case. Record the numbers in the Implementation log.

### S7: First office use case, added without Python

**Build**, following *Adding a use case*:
- Mock data `data/<name>.json` with illustrative values only, clearly not real customer data.
- A provider declaration `data/providers/<provider>.json`.
- A template `templates/<id>/` in VDS components, with its manifest.
- At least three DECIDE eval rows: a plain request, one per important param, and one explorer row.
- Run `npm test` and the decision evals. Rerun the whole decision set, not just the new rows. A new template
  changes DECIDE's prompt for every request (see *Gotchas*).

**Done when:** the new use case works in the client (the plain request, a filtered request, and a REFINE on it),
no `.py` file changed, and the decision evals still pass twice in a row.

### S8: Cut-over: retire the Express backend, full walkthrough

**Build**
- Every client call goes to the new backend. Stop the Express backend and remove its code and scripts.
- Remove the reference templates and data (`plan-*`, `order-history`, `plans.json`, `addons.json`,
  `orders.json`, `orders.list.json`) once office use cases cover the same features (a filtered list, a UI action
  leading to a next screen, a flow that ends in text). Update the tests and eval rows that named them.

**Done when**, in the client with no Express process running:
1. Assistant: a TEXT question, a TEMPLATE request with a filter, a UI action that leads to the next screen, a
   GENERATE request with citations in the trace, a REFINE of that generated UI.
2. Explorer: a baseline → a request that changes a list item ("make the first item's badge red": only that item
   changes, as a new variant card) → a structural request (baseline plus up to 3 variant cards, each listing
   any missing data) → "on variant 2, …" (a new "Variant 2 · rev 2" card, others unchanged).
3. Restart the backend mid-conversation: memory survives.

---

## How the pieces work

Implementation notes for the copied code. Read the module docstrings for the rest.

**DECIDE** (`decide/decide.py`): one structured call over the persona's templates (id, title, intent, examples,
provider params with their choices), all providers, the strategies the persona may use, and the turn context
(a UI action and its source template's `suggestedNext` as hints, the surfaces on screen with their labels and
"option N" aliases, and the user's selections so far). Rules in the prompt that matter:
- TEMPLATE only when a template's intent covers what the user wants to see.
- **Coverage is full only when every need is met by the template's intent or a provider param.** A need no param
  can express (the user's situation, "which one suits me") is a gap, so the answer is GENERATE. This rule keeps
  decisions stable as the template list grows.
- TEXT for conceptual questions. Choosing among options isn't conceptual.
- Data comes from providers. For GENERATE, list the providers whose data the UI needs.
- The explorer rules: ADAPT needs an explicit change instruction, and REFINE targets must be on screen.

**POLICY** (`decide/policy.py`): plain code. It drops strategies the persona can't use (with the fallbacks in
`FALLBACKS`), needs a usable template for TEMPLATE and ADAPT and an on-screen target for REFINE (a missing
target falls back to the latest surface), fills provider params DECIDE left out from the thread's `selections`
(an id from a click comes from the click, never the model), and keeps only known providers.

**TEMPLATE** (`templates/render.py`): loads the template, calls its provider with the params, inserts
`updateDataModel {path: "/", value: data}` after `createSurface`, and runs the graph check and the gate. A
template that fails the gate is a bug the tests should have caught.

**UI actions:** manifests declare the `events` their surface emits and what each means. After an action, DECIDE
sees the source screen and its `suggestedNext` templates as hints, not a state machine. A screen with no
`suggestedNext` ends its flow: the agent acknowledges the choice in TEXT.

**GENERATE** (`ground/ground.py`, `generation/generate.py`): GROUND runs `guidelines.search` (RAG), asks the MCP
server for components matching the best pattern or the request, loads the providers DECIDE listed, and writes a
**design brief** (pattern, components, layout, cited rules, data use). The generator builds from the request
plus the brief and the real data. VERIFY runs the graph check, the schema gate, the hard-rule lints and then
the judge (soft rules, fast model). Failures go back as repair instructions quoting the errors or the cited
rule. The assistant repairs soft-rule findings. The explorer ships the first valid surface with its findings as
flags.

**ADAPT** (`graph/explore.py`, `explore/variants.py`): renders the baseline template and emits it first. Then
one call proposes N variants, each `{title, rationale, sources, missingData, patch}`. Patches are RFC 6902
against a `{components: {id: {...}}}` view, and only `/components/...` may change. Each variant is verified
and repaired on its own (patch applies, graph check, gate, lints, **data contract**: every binding must be a
provider field, judge). Variants are emitted in the order they pass. The prompt carries only the schemas the
screen uses, the MCP suggestions and `COMMON_COMPONENTS`, not the whole catalog.

**REFINE** (`explore/modify.py`): sends the target surface's complete component list plus the request, and gets
back **only the changes**: `update` (props merged in), `add`, `remove`, `newState` (UI state for new inputs) and
`split` (code gives specific list items their own copies, so the model never writes copies). Code applies them,
runs the checks (graph, gate, lints, data contract against the surface's own data, targeting, no stray
components), repairs, computes the diff, and judges only the change. Findings the base screen already had are
dropped. It works on any surface, templated or generated.

**Lineage** (`explore/lineage.py`, state `surfaces`): one record per surface shown (`baseline-N`, `var-N`,
`ui-N`) with its current document and per-revision patches. Refining a baseline starts a new variant, so the
production screen is never edited. The records are checkpointed with the thread.

**Providers** (`data/providers.py`, `data/declared.py`): `REGISTRY` is a live mapping of code providers plus
declared ones, re-read when a declaration or data file changes. Each provider has typed params (coerced, unknown
ones dropped, string choices matched case-insensitively), a `describe()` for DECIDE, and a **field schema**
(every JSON pointer it can return, `*` for array items). Templates, variants and REFINE may bind only to those
fields.

---

## Adding a use case

A use case is data, a provider declaration, a template and eval rows. None of it is Python.

### 1. Data: `data/<name>.json`

A JSON file with a list of objects, anywhere inside it. Use illustrative values, add a `"_note"` saying so, and
keep display-ready text (a status label, a delivery message) as fields when a real API would return it that way.

### 2. Provider declaration: `data/providers/<provider>.json`

The file name without `.json` is the provider name (e.g. `orders.list`). Format:

```json
{
  "description": "One line DECIDE reads: what the list is and its default order.",
  "source": { "file": "orders.json", "list": "/orders" },
  "sort": { "by": "placedOn", "order": "desc" },
  "params": {
    "status":   { "type": "string", "description": "Only orders with this status.",
                  "filter": { "op": "eq", "field": "status" }, "choices": "data", "label": "with status {value}" },
    "minTotal": { "type": "number", "description": "Only orders of at least this many dollars.",
                  "filter": { "op": "gte", "field": "total" }, "label": "of ${value:g} or more" },
    "item":     { "type": "string", "description": "Only orders containing a product whose name includes this text.",
                  "filter": { "op": "contains", "field": "items/*/name" }, "label": "containing \"{value}\"" },
    "openOnly": { "type": "boolean", "description": "Only orders not yet delivered.",
                  "filter": { "op": "ne", "field": "status", "value": "Delivered" }, "label": "still open" },
    "limit":    { "type": "number", "description": "Show only this many of the most recent orders.",
                  "filter": { "op": "limit" } }
  },
  "computed": {
    "totalLabel": "${total:,.2f}",
    "placedLabel": "Placed {placedOn:date}",
    "items/*/label": "{quantity} × {name}"
  },
  "summary": {
    "all": "All {total} orders, newest first.",
    "filtered": "{count} of {total} orders {filters}.",
    "empty": "No orders {filters}."
  }
}
```

| Part | Meaning |
|---|---|
| `source.list` | JSON pointer to the list in the data file. The output key is its last segment (`orders`). |
| `sort` | Optional. Items missing the field go last. |
| `params.<name>.type` | `string`, `number` (accepts `$1,000`) or `boolean`. `required: true` makes it mandatory. |
| `filter.op` | `eq`, `ne`, `lt`, `lte`, `gt`, `gte`, `contains` (case-insensitive substring) or `limit` (keep the first N after sorting; no field). Numbers compare as numbers, everything else as text, so ISO dates order correctly. |
| `filter.field` | Pointer relative to one item. `*` means every array element, and the filter passes when **any** value matches (`ne`: when none does). |
| `filter.value` | Makes the param an **on/off switch** (type `boolean`): when true, the filter applies with this fixed value. |
| `choices` | `"data"` = every value of the filter field in the data, or a list. Shown to DECIDE and enforced. |
| `label` | How the active filter reads in the summary. `{value}` is the param value. |
| `computed` | Display fields added to each item (or to nested objects, `items/*/label`). Placeholders are `{field}` or `{field:spec}`: a Python number format (`,.2f`, `g`), `date` ("Sep 2, 2026") or a strftime pattern for ISO dates. |
| `summary` | Sentences for no filter, some filters and no results. `{count}`, `{total}` and `{filters}` (active labels joined with "and"). |

**Output:** `{ "<list>": [items…], "count": n, "summary": "…" }`. **The field schema is derived**: the
registry runs the provider with every param (sample values taken from the data) and records every pointer it
returns. Templates can bind only to those.

**Checked when the declaration loads:** filter and sort fields exist in the data, computed placeholders exist on
some item, op and type fit (switch ⇔ boolean, choices only on strings), and the name matches the file and
doesn't shadow a code provider. A broken declaration is skipped and printed at startup, and
`test_every_provider_declaration_loads` fails. The server keeps running.

**When to write a code provider instead** (`data/providers.py`, a `Provider` with a `read` function): when the
output needs logic the format can't express, such as joins across data files, conditional labels, or filtering
by another dataset (e.g. "add-ons available for this plan"). Declare the field set explicitly, and add its param
cases to `CODE_PROVIDER_CASES` in `tests/test_templates.py`.

### 3. Template: `templates/<id>/`

`surface.json`: A2UI messages with **no data**, surface id `"main"`:
- `createSurface`, then `updateComponents` with a flat list and one `root`.
- Bind every value from data: `{ "path": "/summary" }` at the top level, and relative paths
  (`{ "path": "name" }`) inside a list template `children: { "path": "/orders", "componentId": "order-tile" }`.
  Nested lists work the same way.
- Literal text only for UI labels (headings, button labels, fine print).
- Actions: `"action": { "event": { "name": "select_order", "context": { "orderId": { "path": "id" } } } }`.
  Every event must be declared in the manifest.
- Use only VDS components and props. Choose containers that can hold the content: if a component has no
  `children` prop, its body can't go inside it.

`manifest.json`:

```json
{
  "id": "order-history", "version": 1,
  "title": "Order history",
  "intent": "Show the customer's orders, newest first, each with its status, total, date and items, optionally filtered by status, total, a product in the order, or only the latest few",
  "examples": ["show my orders", "my delivered orders", "orders over $100", "my last 3 orders"],
  "personas": ["assistant", "explorer"],
  "data": { "provider": "orders.list" },
  "caption": "Here are your orders.",
  "events": { "select_order": "The user opened one order (context: orderId)." },
  "suggestedNext": ["order-detail"]
}
```

(`select_order` and `order-detail` illustrate a two-screen flow. The reference `order-history` template has no
event. Every template named in `suggestedNext` must exist.)

- `intent` is what DECIDE matches against. Name what the screen shows and every way it can be narrowed (those
  should be provider params).
- `examples` are typical requests, including filtered ones.
- `events` names each event the surface emits and what it means. `suggestedNext` lists templates that usually
  follow; they're hints for DECIDE. An empty list means an action on this screen ends the flow in text.
- The folder name must equal `id`. Bump `version` when the layout changes.

### 4. Eval rows: `server/evals/decisions.jsonl`

One JSON object per line:

```json
{"prompt": "show my orders", "persona": "assistant", "expect": {"strategy": "TEMPLATE", "templateId": "order-history"}}
{"prompt": "which of my orders were delivered?", "persona": "assistant", "expect": {"strategy": "TEMPLATE", "templateId": "order-history", "params": {"status": "delivered"}}}
{"prompt": "did I buy any headphones?", "persona": "assistant", "expect": {"strategy": "TEMPLATE", "templateId": "order-history", "shows": {"orders": ["ord-1047"]}}}
{"action": {"name": "select_order", "context": {"orderId": "ord-1047"}}, "persona": "assistant", "expect": {"strategy": "TEMPLATE", "templateId": "order-detail", "params": {"orderId": "ord-1047"}}}
```

- `params` compares the decided value (lowercased, `$` and `.0` stripped).
- `shows` compares **what the provider returns** for the decided params (item ids in order). Use it when
  several wordings are equally right ("headphone" and "headphones" find the same order).
- `selections` (the user's earlier choices) and `surfaces`/`latest` (what's on screen, for REFINE rows) add
  context.

### 5. Check

`npm test` gates the template with every param case, checks each binding against the provider's fields, checks
the declared events, and checks that `suggestedNext` templates exist. Then run the decision evals (all rows).
Declarations, data files and templates are re-read when they change, so the running server picks them up
without a restart.

---

## Tests and evals

| Suite | Guards | Port work |
|---|---|---|
| `test_contract.py` | Exact AG-UI event sequences (text, UI, gate failure, actions, trace, guideline repair) with fake models | VDS components in fixture docs. Fakes replace the LangChain models, so the Anthropic switch only changes how models are injected. The grounding tests build `Guidelines([LocalGuidelines()])`: give them a fake guideline source returning fixed `Source`s instead, and let the hard-rule repair test register a test-only lint. |
| `test_gate.py` | Validator semantics: undeclared props rejected, bindings accepted on dynamic props, layout components reported as unknown | Re-express every case with VDS components and props. |
| `test_graph_check.py` + `fixtures/graph_check/` | Orphan, root, duplicate-id and list-template repair | Unchanged (component-agnostic). |
| `test_prompt_parity.py` + `fixtures/system_prompt.node.txt` | The generator prompt as a snapshot | Refresh with `UPDATE_SNAPSHOTS=1` after the S1 prompt edits, and review the diff. |
| `test_templates.py` | Every template gates with every param case, bindings ⊂ provider fields, events declared, `suggestedNext` exists, providers load | Unchanged. Code-provider cases in `CODE_PROVIDER_CASES`. |
| `test_declared_providers.py` | The declaration engine on a neutral fixture domain | Unchanged. |
| `test_policy.py` | Every disallowed strategy falls back correctly | Unchanged. |
| `test_explore.py` | Patching, lineage, variants and REFINE with fake models | VDS components in fixtures. |
| `test_verify.py` | Lints and guideline sources | Replace with: the lint registry's contract (every entry has id, title, text, check), the RAG adapter (`_parse` on a sample `{answers, citations}` body), and a RAG failure giving a note, not an exception. |
| `test_llm.py` | `parse_json` tolerance; an unusable reply is a retried attempt | Replace the OpenAI parameter tests with: refusal and max_tokens become `ValueError`, and thinking blocks are skipped when reading text. |
| `test_generate_endpoint.py` | `/generate` 200/400/422/500 | Unchanged. |
| `test_decide_eval.py` (`-m eval`) | Real-model decisions from `evals/decisions.jsonl` | Rows for office use cases (S7). |
| `test_modify_eval.py` (`-m eval`) | Real-model REFINE on non-template screens (a list, a form, a grid, a dashboard): the right items change and only those, no data copied as text, new inputs bound to new state | Re-express `evals/modify_cases.py` screens in VDS components. Keep every check. |

`pytest` excludes `-m eval` by default (`addopts = "-m 'not eval'"`). The evals run only on demand:
`cd server && uv run pytest -m eval`.

---

## Gotchas

1. **Undeclared props are rejected.** Every catalog component declares `unevaluatedProperties: false`, so the
   gate rejects props the schema doesn't declare. The repair loop fixes these from the exact error text.
   jsonschema nests errors under `allOf`, and a failed branch makes `unevaluatedProperties` also flag valid
   props. `gate.py` rewrites that error to list only props the schema never declares. Keep that.
2. **Layout components aren't in `catalog.json`.** `Column`, `Row`, `List` and `Divider` are reported as
   `unknownComponents`, not schema-validated. Their `$ref`s point at a remote URL that must never be fetched at
   runtime.
3. **No prefill, no temperature.** Current Claude models return a 400 for an assistant prefill or sampling
   parameters. JSON comes from the prompt's output contract plus `parse_json` plus the gate.
4. **Prompt caching is a prefix match.** The generator's system prompt must be byte-identical across calls:
   build it once from the catalog and cache it (`@cache`). Anything per-request (the user's request, the brief,
   data) goes in the user message, never the system prompt. Check `cacheRead` in the trace.
5. **Server-side refusal fallbacks are a beta.** `fallbacks="default"` needs the `server-side-fallback-2026-07-01`
   beta header. If the enterprise endpoint rejects it (a 400 naming the header or `fallbacks`), remove the two
   arguments. The `stop_reason == "refusal"` check stays either way.
6. **Only the responder's tokens are chat text.** The bridge maps `on_chat_model_stream` events whose
   `metadata["langgraph_node"] == "responder"`, and only the `text` parts of a chunk. The structured calls
   (DECIDE, brief, judge) are LangChain calls too, so never widen that filter.
7. **Custom events:** nodes use `adispatch_custom_event` and the bridge consumes `graph.astream_events(..., version="v2")`.
   Python ≥3.11 propagates the run config automatically. Stay on 3.12.
8. **Windows + async psycopg** needs the Selector event loop. Uvicorn ≥0.36 takes it from the loop factory
   (`loop="app.loops:selector_loop_factory"` in `run.py`), not from the asyncio policy.
9. **Aurora:** use the writer endpoint (the checkpointer writes on every turn), TLS (`sslmode=require` or
   stricter), and the pool's connection check. The first start needs CREATE TABLE rights.
10. **Every template changes every decision.** DECIDE sees all templates, so a new one can shift unrelated
    decisions (a longer template list makes it more template-happy on borderline requests). Rerun the whole
    decision set after adding a template, and fix drift with a generic rule, never a domain example.
11. **The MCP server and the gate must use the same catalog version**, or the brief suggests components the gate
    rejects.
12. **Never print secrets.** Log the database host and name only, and never the Anthropic key, the MCP headers
    or the RAG body.

---

## Known limitations

- **GENERATE is the slowest path**: a brief, a full-catalog generation and a judge call. Most turns that show a
  curated screen or refine one take seconds, while a generated screen with repairs can take much longer.
  `LLM_EFFORT=low`, prompt caching and `GUIDELINE_JUDGE=off` are the levers. Measure with the trace timings
  before changing anything.
- **The judge reviews what changed, but a structural change can look new.** When REFINE splits a list into
  per-item copies, a finding the base screen already had (e.g. about the number of tiles) can be reported
  against the variant.
- **"Variant N" versus "item N"** is ambiguous in requests like "on variant 2, make the badge say X". DECIDE
  targets variant 2 correctly, but the change may land on the second item only. Add an eval row when this
  matters for office screens.
- **Two baseline records can share a label** after an ADAPT, which re-emits the baseline. The caption's
  "Unchanged:" list then repeats it.

---

## Commands

```bash
# server
cd server && uv sync
npm run agui                              # from the repo root: the backend on :8090
uv run python run.py --port 8091          # a second instance (side-by-side)
npm test                                  # from the repo root: the default suite (no model calls)
UPDATE_SNAPSHOTS=1 npm test               # after an intentional prompt or catalog change (bash)
cd server && uv run pytest -m eval        # real-model decision + modify evals (costs API calls)

# client
cd client && npm run dev                  # http://localhost:5176 → Chat and Generate UI tabs
```

---

## Out of scope

Authentication, deployment and containers for the backend, running the evals in CI, a template object store,
promoting explorer variants into templates, and changes to `@vds/core` itself.

---

## Implementation log

Add one line per completed phase: date, phase, what was verified in the client, and anything that differs from
this document (and why).
