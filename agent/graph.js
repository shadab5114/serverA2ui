// Phase 4 — Generative-UI core: router -> (responder | uiGenerator).
//
// The graph now branches. The router classifies each turn as "text" or "ui":
//   - responder:   streams a plain-text answer (Phase 3 behavior).
//   - uiGenerator: runs the validator-gated A2UI generate+repair loop
//                  (see ./uiGenerator.js) and DISPATCHES the result as custom
//                  events the AG-UI server bridges onto the wire:
//                    "a2ui"             -> AG-UI CUSTOM event (the surface)
//                    "assistant_text"   -> AG-UI TEXT_MESSAGE_* (chat caption)
//                  If generation never validates, it degrades to a plain-text
//                  apology (still via "assistant_text") instead of crashing.
//
// Conversation memory is provided by a checkpointer keyed by thread_id (Phase 3).
// Custom events are surfaced through graph.streamEvents() as on_custom_event.

import {
  Annotation,
  MessagesAnnotation,
  StateGraph,
  START,
  END,
  MemorySaver,
} from "@langchain/langgraph";
import { ChatOpenAI } from "@langchain/openai";
import { AIMessage, HumanMessage, SystemMessage } from "@langchain/core/messages";
import { dispatchCustomEvent } from "@langchain/core/callbacks/dispatch";
import { generateValidatedA2UI } from "./uiGenerator.js";

const SYSTEM_PROMPT =
  "You are a concise, friendly assistant inside a generative-UI app. " +
  "Answer in plain text. Keep replies short unless asked for detail.";

// Router classifier prompt. The router only decides the branch — it must reply
// with exactly one bare word so parsing is trivial and robust.
const ROUTER_PROMPT =
  "You are a router in a generative-UI app. Decide whether the user's latest " +
  "message asks you to BUILD or SHOW a piece of UI (a form, card, list, table, " +
  'dashboard, sign-up/login screen, settings panel, etc.) — answer "ui" — or ' +
  'is just a conversational/informational message — answer "text". ' +
  "Reply with exactly one word: ui or text.";

/** Graph state: the running message list (MessagesAnnotation) + the route. */
export const GraphState = Annotation.Root({
  ...MessagesAnnotation.spec,
  route: Annotation(), // "text" | "ui"
});

/** Streaming chat model for the responder (token deltas flow to the client). */
function makeModel() {
  const model = process.env.OPENAI_MODEL || "gpt-4o";
  // gpt-5 / o-series only accept the default temperature (1); older models are
  // fine with 1 too, so set it explicitly to keep one code path.
  return new ChatOpenAI({ model, temperature: 1, streaming: true });
}

/** Non-streaming, cheap model for routing. Its tokens never reach the user. */
function makeRouterModel() {
  const model = process.env.ROUTER_MODEL || process.env.OPENAI_MODEL || "gpt-4o-mini";
  return new ChatOpenAI({ model, temperature: 1, streaming: false });
}

/** Text of the newest human message in state. */
function lastUserText(state) {
  const messages = state.messages || [];
  for (let i = messages.length - 1; i >= 0; i--) {
    const m = messages[i];
    const isHuman = m instanceof HumanMessage || m?._getType?.() === "human" || m?.role === "user";
    if (isHuman) {
      const c = m.content;
      return typeof c === "string" ? c : Array.isArray(c) ? c.map((p) => p?.text ?? "").join("") : "";
    }
  }
  return "";
}

/**
 * Router node: classify this turn as "ui" or "text". Falls back to "text" on any
 * classifier error so a routing hiccup can never break the conversation.
 */
function makeRouter(routerModel) {
  return async function router(state) {
    const userText = lastUserText(state);
    try {
      const reply = await routerModel.invoke([
        new SystemMessage(ROUTER_PROMPT),
        new HumanMessage(userText),
      ]);
      const word = String(reply?.content ?? "").toLowerCase();
      return { route: word.includes("ui") ? "ui" : "text" };
    } catch {
      return { route: "text" };
    }
  };
}

/** Responder node: stream a plain-text answer from the LLM (Phase 3 path). */
function makeResponder(model) {
  return async function responder(state) {
    const reply = await model.invoke([new SystemMessage(SYSTEM_PROMPT), ...state.messages]);
    return { messages: [reply] };
  };
}

/**
 * UI-generator node: run the validator-gated generate+repair loop, then dispatch
 * the outcome as custom events. Returns an AIMessage into state so the
 * checkpointer records what the assistant did this turn.
 */
async function uiGenerator(state) {
  const userText = lastUserText(state);

  // UI generation is a single (non-streamed) LLM call plus possible repair
  // retries — several seconds with nothing on the wire. Emit an early status so
  // the client shows progress instead of appearing frozen.
  await dispatchCustomEvent("status", { text: "Generating UI…" });

  const result = await generateValidatedA2UI(userText);

  if (result.ok) {
    // The surface itself → bridged to an AG-UI CUSTOM event by the server.
    await dispatchCustomEvent("a2ui", { a2ui: result.a2ui.a2ui, meta: result.meta });
    const caption = "Here's the UI you asked for.";
    await dispatchCustomEvent("assistant_text", { text: caption });
    // Persist a compact record (not the whole surface) in chat history.
    return { messages: [new AIMessage(caption)] };
  }

  // Validator gate never passed → degrade to text instead of emitting broken UI.
  const apology =
    "I couldn't build a valid UI for that. Could you rephrase or simplify the " +
    "request? (The generated layout didn't pass validation.)";
  await dispatchCustomEvent("assistant_text", { text: apology });
  return { messages: [new AIMessage(apology)] };
}

/** Pick the next node from the router's decision. */
function routeEdge(state) {
  return state.route === "ui" ? "uiGenerator" : "responder";
}

/**
 * Build and compile the graph.
 * @param {object} [opts]
 * @param {import("@langchain/langgraph").BaseCheckpointSaver} [opts.checkpointer]
 *   Persistence for resume-by-thread_id. Defaults to an in-memory MemorySaver.
 */
export function buildGraph({ checkpointer = new MemorySaver() } = {}) {
  const model = makeModel();
  const routerModel = makeRouterModel();

  const workflow = new StateGraph(GraphState)
    .addNode("router", makeRouter(routerModel))
    .addNode("responder", makeResponder(model))
    .addNode("uiGenerator", uiGenerator)
    .addEdge(START, "router")
    .addConditionalEdges("router", routeEdge, {
      responder: "responder",
      uiGenerator: "uiGenerator",
    })
    .addEdge("responder", END)
    .addEdge("uiGenerator", END);

  return workflow.compile({ checkpointer });
}
