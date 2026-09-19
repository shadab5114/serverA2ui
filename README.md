# GenUI playground

A playground for **generative UI grounded in a design system**. You type a prompt, and an agent either answers
in text or builds a UI. The UI is emitted as **A2UI v0.9** JSON, streamed over **AG-UI** (SSE), and rendered by
React with real components from **`@shadab5114/pds-core`**. The design system's `catalog.json` grounds the agent:
it's embedded in the generator's prompt, and every generated component is validated against it before it
reaches the screen.

```
client/  (React, Vite :5176)  ──/agui/run (SSE)──▶  server/  (Python: FastAPI + LangGraph, :8090)  ──▶  OpenAI
                               ──/generate (JSON)──▶      │
                                                          └─▶ Postgres (chat memory, database a2ui_py)
```

The plan, status and design decisions for the backend live in **[PYTHON-BACKEND-PLAN.md](PYTHON-BACKEND-PLAN.md)**.

## Prerequisites

- **Node** (for the client, and to install the design system package that ships `catalog.json`)
- **Python 3.12** and **[uv](https://docs.astral.sh/uv/)**
- **Docker Desktop** (Postgres for durable chat memory; optional, the server falls back to in-memory)
- `NODE_AUTH_TOKEN` with read access to GitHub Packages (`@shadab5114/pds-core`, see `.npmrc`)

## Setup (once)

```bash
npm install                       # root: installs @shadab5114/pds-core (the server reads its catalog.json)
cd client && npm install && cd ..
cd server && uv sync && cd ..

cp .env.example .env              # then set OPENAI_API_KEY
cp server/.env.example server/.env

npm run db:up                     # Postgres in Docker (container a2ui-postgres)
docker exec a2ui-postgres createdb -U a2ui a2ui_py
```

## Run

```bash
npm run agui                      # backend on http://localhost:8090
cd client && npm run dev          # client on http://localhost:5176
```

Open http://localhost:5176:
- **Chat**: conversation with memory. Ask a question to get text, or ask for a UI ("show me a sign-up form with
  email, password and a submit button") to get a rendered surface. UI turns take ~20–30 s.
- **Generate UI**: one prompt → one A2UI document, shown as JSON and rendered. Or paste A2UI JSON and click Render.

The server log prints one readable line per step: route decision, each generation attempt, validator rejections
and repairs.

## How a UI turn works

1. **Router** (small model) classifies the message as `text` or `ui`.
2. **Generator** asks the model for A2UI JSON (JSON mode), with the full catalog in the system prompt.
3. **Graph check** repairs orphaned components and root wiring.
4. **Validator gate** checks every component against `catalog.json` (JSON Schema 2020-12). Undeclared props,
   bad enum values and wrong types are rejected.
5. On rejection, the exact errors go back to the model (**repair loop**, `A2UI_MAX_REPAIRS`, default 2). If it
   never passes, the user gets an apology in text, never a broken UI.

## Adding a use case (no Python)

A curated screen needs three files and no code. `order-history` is the worked example.

1. **Data**: `data/<name>.json`, illustrative mock data with a list of objects (e.g. `data/orders.json`).
2. **Provider declaration**: `data/providers/<provider>.json` names that file and list, the params DECIDE may
   pass and how each one filters (`eq`, `ne`, `lt`, `lte`, `gt`, `gte`, `contains`, `limit`, or an on/off switch),
   optional sorting, computed display fields (`"${total:,.2f}"`, `"{placedOn:date}"`) and summary sentences. The
   field schema is read off the data, so templates can bind only to what really exists. The format is documented
   at the top of `server/app/data/declared.py`. Complex providers can still be written in code
   (`server/app/data/providers.py`); both kinds load side by side.
3. **Template**: `templates/<id>/surface.json` (A2UI with data bindings) and `manifest.json` (intent, examples,
   personas, `data.provider`).

Then add a row to `server/evals/decisions.jsonl` and run `npm test`: every template is gated, its bindings are
checked against the provider's fields, and every declared param is exercised with values taken from the data.
Templates, declarations and the data files they read are re-read when they change, so the running server picks
them up without a restart. A broken declaration is skipped and printed at startup, and it fails the tests.

## Test

```bash
npm test                          # = cd server && uv run pytest
```

Includes wire-contract tests (event order the client depends on), the validator gate, and snapshot tests of the
system prompt and graph check. After an intentional catalog or prompt change, refresh the prompt snapshot with
`UPDATE_SNAPSHOTS=1 npm test`.

## Endpoints (all on :8090)

| Method | Path           | Purpose |
|--------|----------------|---------|
| POST   | `/agui/run`    | AG-UI run: `{threadId, runId, messages}` → SSE stream of AG-UI events |
| GET    | `/agui/health` | status, phase, checkpointer kind |
| POST   | `/generate`    | `{prompt}` → `{meta, a2ui}` (validated); 422 with the validator errors if it never passes |
| GET    | `/health`      | status, provider |

## Configuration

Root `.env` holds the shared keys; `server/.env` overrides them (it points `DATABASE_URL` at `a2ui_py`).

| Key | Default | Notes |
|---|---|---|
| `OPENAI_API_KEY` | (required) | |
| `OPENAI_MODEL` | `gpt-4o` | responder + generator |
| `ROUTER_MODEL` | `OPENAI_MODEL`, else `gpt-4o-mini` | set a small model to keep routing fast |
| `OPENAI_MAX_TOKENS` | `6000` | generator completion cap |
| `LLM_PROVIDER` | `openai` | `anthropic` needs `uv add anthropic` in `server/` and `ANTHROPIC_API_KEY` |
| `DATABASE_URL` | unset → in-memory | `postgresql://a2ui:a2ui@localhost:5432/a2ui_py` |
| `A2UI_MAX_REPAIRS` | `2` | `0` = no retries |
| `AGUI_PORT` | `8090` | `uv run python run.py --port N` overrides |
| `LOCAL_CATALOG_PATH` | `node_modules/@shadab5114/pds-core/catalog.json` | |
| `TEMPLATES_DIR` | `templates/` | curated templates |
| `DATA_DIR` | `data/` | mock data the providers read |
| `PROVIDERS_DIR` | `DATA_DIR/providers/` | declared data providers, one JSON file each |

## History

The backend was first built in Node (`agent/`, `agui/`, `src/`) and ported to Python with identical behavior
(PYTHON-BACKEND-PLAN.md, P0–P4). The Node code is gone from the tree but remains in git history.
`A2UI-BACKEND-ARCHITECTURE.md` is kept for its concepts.
