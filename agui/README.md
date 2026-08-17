# AG-UI server — Phase 1 (raw SSE, no LangGraph)

Fastify endpoint that **hand-emits the AG-UI lifecycle** over SSE so you can see
the event protocol at the byte level before LangGraph / `@ag-ui/langgraph`
hides it. No LLM, no catalog — the assistant reply is faked and streamed token
by token.

See the phase plan in [`../A2UI-BACKEND-ARCHITECTURE.md`](../A2UI-BACKEND-ARCHITECTURE.md)
and the layout mapping in [`../docs/phase-0-architecture-mapping.md`](../docs/phase-0-architecture-mapping.md).

## Run

```bash
npm run agui        # node agui/server.js   (or npm run agui:dev to watch)
```

Then open <http://localhost:8090/> and click **Run turn**. The left panel shows
the rendered conversation; the right panel shows the raw AG-UI event log.

Port override: `AGUI_PORT=8090`.

## Endpoints

| Method | Path           | Purpose                                            |
| ------ | -------------- | -------------------------------------------------- |
| GET    | `/`            | Minimal SSE test client (`test-client.html`)       |
| GET    | `/agui/health` | Liveness                                           |
| POST   | `/agui/run`    | AG-UI `RunAgentInput` → SSE stream of AG-UI events  |

## Event sequence emitted

```
RUN_STARTED
  TEXT_MESSAGE_START        (role: assistant)
  TEXT_MESSAGE_CONTENT × N  (streamed word-by-word deltas)
  TEXT_MESSAGE_END
RUN_FINISHED
```

Events are serialized with `@ag-ui/encoder`'s `EventEncoder.encodeSSE()` and
typed via `@ag-ui/core`'s `EventType`. Client disconnects are detected on the
**response** socket so the stream stops emitting when the browser goes away.

## Quick curl check

```bash
curl -N -X POST http://localhost:8090/agui/run \
  -H 'Content-Type: application/json' \
  -d '{"threadId":"t1","runId":"r1"}'
```

## Not yet (later phases)

- Phase 2: catalog compiler (Zod v4 schemas + TS types + prompt reference).
- Phase 3: real LangGraph graph + Postgres checkpointer.
- Phase 4: A2UI generator + validator gate, streamed as AG-UI **UI** events and
  rendered by the existing `client/` React app.
