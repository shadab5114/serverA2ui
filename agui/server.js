// Phase 4 — Generative UI over AG-UI.
//
// The AG-UI SSE endpoint runs the branching LangGraph graph (router ->
// responder | uiGenerator; see ../agent/graph.js). graph.streamEvents() surfaces
// are bridged onto the AG-UI lifecycle two ways:
//
//   TEXT branch (responder) — token deltas:
//     RUN_STARTED -> TEXT_MESSAGE_START -> TEXT_MESSAGE_CONTENT* -> TEXT_MESSAGE_END -> RUN_FINISHED
//
//   UI branch (uiGenerator) — custom events dispatched inside the node:
//     "a2ui"           -> AG-UI CUSTOM event carrying the validated A2UI messages
//     "assistant_text" -> a one-shot TEXT_MESSAGE_START/CONTENT/END (chat caption
//                          or the text fallback when generation didn't validate)
//
// Only the responder's own token stream becomes chat text (filtered by
// langgraph_node) so the router's classifier tokens never leak to the user.
//
// Conversation memory is keyed by AG-UI threadId (mapped to the graph's
// thread_id checkpoint), persisted by the checkpointer (Postgres or in-memory).

import "dotenv/config";
import Fastify from "fastify";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { randomUUID } from "node:crypto";
import { EventType } from "@ag-ui/core";
import { EventEncoder } from "@ag-ui/encoder";
import { HumanMessage } from "@langchain/core/messages";
import { requestLogger } from "../src/logger.js";
import { buildGraph } from "../agent/graph.js";
import { getCheckpointer } from "../agent/checkpointer.js";

const __dirname = dirname(fileURLToPath(import.meta.url));
const PORT = process.env.AGUI_PORT || 8090;

// Fastify's built-in logger emits one JSON line per request; we log a readable
// flow trace ourselves instead (see requestLogger).
const fastify = Fastify({ logger: false });

// One shared graph instance. Its checkpointer (Postgres if DATABASE_URL is set,
// else in-memory) persists conversation state across requests keyed by thread_id.
const { checkpointer, kind: checkpointerKind, detail: checkpointerDetail } =
  await getCheckpointer();
const graph = buildGraph({ checkpointer });

/** Pull plain text out of a LangChain message chunk's content (string or parts). */
function chunkText(content) {
  if (typeof content === "string") return content;
  if (Array.isArray(content)) {
    return content
      .map((p) => (typeof p === "string" ? p : p?.type === "text" ? p.text : ""))
      .join("");
  }
  return "";
}

/** Health / liveness. */
fastify.get("/agui/health", async () => ({
  status: "ok",
  phase: 4,
  endpoint: "/agui/run",
  checkpointer: checkpointerKind,
}));

/** Serve the minimal test client from the same origin (no CORS needed). */
fastify.get("/", async (_req, reply) => {
  const html = await readFile(join(__dirname, "test-client.html"), "utf8");
  reply.type("text/html").send(html);
});

/**
 * POST /agui/run
 * Body: AG-UI RunAgentInput { threadId, runId, messages, state, ... }
 * Returns: an SSE stream of AG-UI events driven by the LangGraph graph.
 */
fastify.post("/agui/run", async (request, reply) => {
  const log = requestLogger("/agui/run");
  const encoder = new EventEncoder();
  const input = request.body || {};

  // Fall back to server-generated ids so the endpoint works even from a raw
  // curl that omits them.
  const threadId = input.threadId || `thread_${randomUUID()}`;
  const runId = input.runId || `run_${randomUUID()}`;
  const messageId = `msg_${randomUUID()}`;

  // Only the newest user message is fed in; prior turns are restored from the
  // checkpointer by thread_id.
  const lastUser = [...(input.messages || [])].reverse().find((m) => m?.role === "user");
  const userText = String(lastUser?.content ?? "");
  log.start(`SSE run — thread=${threadId}, run=${runId}, user="${userText.slice(0, 60)}"`);

  // Take over the raw socket for manual SSE writes with proper backpressure.
  reply.hijack();
  const res = reply.raw;
  res.writeHead(200, {
    "Content-Type": encoder.getContentType(), // text/event-stream
    "Cache-Control": "no-cache, no-transform",
    Connection: "keep-alive",
    "X-Accel-Buffering": "no", // disable proxy buffering
  });

  // Write one AG-UI event as an SSE frame, respecting backpressure.
  const send = (event) =>
    new Promise((resolve) => {
      const frame = encoder.encodeSSE({ ...event, timestamp: Date.now() });
      if (res.write(frame)) resolve();
      else res.once("drain", resolve);
    });

  // If the client disconnects mid-stream, stop emitting. Listen on the RESPONSE
  // socket, not request.raw — the request (readable) side emits "close" as soon
  // as the POST body is consumed, which would abort the stream immediately.
  let closed = false;
  res.on("close", () => {
    closed = true;
  });

  let started = false; // emitted TEXT_MESSAGE_START for the streaming path yet?
  let deltas = 0;
  let surfaces = 0;

  // Emit one complete assistant text message (start + content + end). Used for
  // the UI branch's caption/fallback, which arrives whole (not token-streamed).
  const sendWholeText = async (text) => {
    if (!text) return;
    const oneShotId = `msg_${randomUUID()}`;
    await send({ type: EventType.TEXT_MESSAGE_START, messageId: oneShotId, role: "assistant" });
    await send({ type: EventType.TEXT_MESSAGE_CONTENT, messageId: oneShotId, delta: text });
    await send({ type: EventType.TEXT_MESSAGE_END, messageId: oneShotId });
  };

  try {
    await send({ type: EventType.RUN_STARTED, threadId, runId });
    log.step("emit RUN_STARTED — invoking graph");

    // Stream the graph. streamEvents(v2) surfaces the responder's token stream as
    // on_chat_model_stream events and the uiGenerator's dispatched custom events
    // as on_custom_event; thread_id gives per-conversation memory.
    const events = graph.streamEvents(
      { messages: [new HumanMessage(userText)] },
      { version: "v2", configurable: { thread_id: threadId } }
    );

    for await (const ev of events) {
      if (closed) break;

      // --- TEXT branch: only the responder node's tokens become chat text.
      // (The router runs an LLM too; scoping by node keeps its output off-wire.)
      if (ev.metadata?.langgraph_node === "responder") {
        if (ev.event === "on_chat_model_start" && !started) {
          await send({ type: EventType.TEXT_MESSAGE_START, messageId, role: "assistant" });
          started = true;
          log.step("responder start → TEXT_MESSAGE_START");
        } else if (ev.event === "on_chat_model_stream") {
          const text = chunkText(ev.data?.chunk?.content);
          if (text) {
            await send({ type: EventType.TEXT_MESSAGE_CONTENT, messageId, delta: text });
            deltas++;
          }
        }
        continue;
      }

      // --- UI branch: custom events dispatched inside the uiGenerator node.
      if (ev.event === "on_custom_event") {
        if (ev.name === "a2ui") {
          // The validated surface → an AG-UI CUSTOM event the client renders.
          await send({ type: EventType.CUSTOM, name: "a2ui", value: ev.data });
          surfaces++;
          const count = ev.data?.a2ui?.length ?? 0;
          log.step(`uiGenerator → CUSTOM a2ui (${count} message(s))`);
        } else if (ev.name === "assistant_text") {
          await sendWholeText(ev.data?.text);
          log.step("uiGenerator → TEXT_MESSAGE (caption/fallback)");
        } else if (ev.name === "status") {
          // Transient progress note (e.g. "Generating UI…"); not chat history.
          await send({ type: EventType.CUSTOM, name: "status", value: ev.data });
        }
      }
    }

    if (closed) {
      log.warn(`client disconnected mid-stream — stopped after ${deltas} deltas`);
    } else {
      if (started) await send({ type: EventType.TEXT_MESSAGE_END, messageId });
      await send({ type: EventType.RUN_FINISHED, threadId, runId });
      log.done(
        `streamed ${deltas} text delta(s), ${surfaces} surface(s) → RUN_FINISHED`
      );
    }
  } catch (err) {
    if (!closed) {
      await send({ type: EventType.RUN_ERROR, message: err?.message || "stream error" });
    }
    log.fail(`graph/stream error — ${err?.message || err}`);
  } finally {
    res.end();
  }
});

fastify.listen({ port: PORT, host: "0.0.0.0" }).then(() => {
  console.log(`AG-UI (Phase 4) listening on http://localhost:${PORT}`);
  console.log(`  test client:      http://localhost:${PORT}/`);
  console.log(`  run endpoint:     POST http://localhost:${PORT}/agui/run`);
  console.log(`  checkpointer:     ${checkpointerDetail}${checkpointerKind === "memory" ? " — chat memory is NOT durable" : ""}`);
});
