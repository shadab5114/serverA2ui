# A2UI LLM Server

An HTTP server that takes a **user prompt** and returns **A2UI JSON** generated
by an LLM. The component **catalog is fetched live from an MCP server on every
request** — the LLM only ever builds UIs from components that actually exist.

- LLM provider is pluggable: **OpenAI now**, Anthropic later (flip one env var).
- A2UI output uses the canonical directives: `createSurface`, `updateDataModel`,
  `updateComponents`.

## How it works

```
POST /generate { prompt }
        │
        ▼
1. Connect to MCP server (MCP_URL) ──► list tools ──► call catalog tool   (runtime, every request)
2. Build system prompt embedding the catalog
3. Call the LLM (OpenAI / Anthropic) with strict JSON output
4. Return the A2UI JSON
```

## Setup

```bash
npm install
```

`.env` is already created. Confirm/adjust:

```
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o
MCP_URL=http://localhost:3939/mcp
PORT=8080
```

> Make sure your MCP server is running at `MCP_URL` (default
> `http://localhost:3939/mcp`) before calling `/generate` — the catalog is read
> from it at request time.

## Run

```bash
npm start
# or: npm run dev   (auto-restart on changes)
```

## Test with Postman / curl

`POST http://localhost:8080/generate`

Body (raw JSON):

```json
{ "prompt": "Create a sign-up form with a name field, an email field, and a submit button." }
```

Example response (real **A2UI v0.9** shape — every message carries `version`,
component types use `component`, props are inline, bindings are JSON Pointers):

```json
{
  "meta": {
    "provider": "openai",
    "model": "gpt-4o",
    "catalogId": "https://pdesign.dev/catalog/v1/catalog.json",
    "components": ["Button", "Text", "TileContainer", "Tilelet", "..."],
    "generatedAt": "2026-06-18T10:00:00.000Z"
  },
  "a2ui": [
    { "version": "v0.9", "createSurface": { "surfaceId": "main", "catalogId": "https://pdesign.dev/catalog/v1/catalog.json" } },
    { "version": "v0.9", "updateDataModel": { "surfaceId": "main", "path": "/", "value": { "shoes": [ { "name": "Sneaker", "price": "120" }, { "name": "Boot", "price": "150" } ] } } },
    { "version": "v0.9", "updateComponents": {
        "surfaceId": "main",
        "components": [
          { "id": "root", "component": "TileContainer", "children": { "path": "/shoes", "componentId": "shoe-tile" } },
          { "id": "shoe-tile", "component": "Tilelet", "title": { "children": { "path": "name" } }, "subtitle": { "children": { "path": "price" } } }
        ]
      }
    }
  ]
}
```

Key A2UI v0.9 rules the server follows:
- Each message has `"version": "v0.9"` and exactly one message key.
- `createSurface` → `surfaceId` + `catalogId` (no `root` here).
- `updateDataModel` → `path` (JSON Pointer, `/` = whole model) + `value`.
- `updateComponents` → flat `components` list; exactly one has `"id": "root"`.
- Components use `component` (the type), props **inline** (no `properties`/`bindings` wrappers).
- Dynamic values are inline DataBindings `{ "path": "/json/pointer" }` (JSON Pointer, e.g. `/shoes/0/name` — not `shoes[0].name`).
- Lists use a template: `children: { "path": "/shoes", "componentId": "tile" }` with relative pointers inside the template.

> Component types and their property shapes come entirely from **your** catalog
> — the server fetches full schemas via `get_component_schema` at runtime, so
> the model can only use real components, real props, and correct shapes.

## Postman quick steps

1. Method `POST`, URL `http://localhost:8080/generate`.
2. Body tab → **raw** → **JSON**.
3. Paste `{ "prompt": "..." }` and **Send**.

## Switching to Anthropic later

1. `npm install @anthropic-ai/sdk`
2. In `.env`: set `LLM_PROVIDER=anthropic`, `ANTHROPIC_API_KEY=...`
   (`ANTHROPIC_MODEL` defaults to `claude-opus-4-8`).
3. Restart. No other code changes needed — see `src/llm.js`.

## Endpoints

| Method | Path        | Purpose                              |
| ------ | ----------- | ------------------------------------ |
| POST   | `/generate` | `{ prompt }` → A2UI JSON             |
| GET    | `/health`   | Liveness + active provider           |

## Config reference

| Env var            | Default                      | Notes                                              |
| ------------------ | ---------------------------- | -------------------------------------------------- |
| `LLM_PROVIDER`     | `openai`                     | `openai` or `anthropic`                            |
| `OPENAI_API_KEY`   | —                            | required for OpenAI                                 |
| `OPENAI_MODEL`     | `gpt-4o`                     |                                                    |
| `ANTHROPIC_API_KEY`| —                            | required for Anthropic                              |
| `ANTHROPIC_MODEL`  | `claude-opus-4-8`            |                                                    |
| `MCP_URL`          | `http://localhost:3939/mcp`  | catalog source                                     |
| `MCP_CATALOG_TOOL` | _(auto-discover)_            | force a specific MCP tool name                      |
| `PORT`             | `8080`                       | HTTP port                                          |
