/**
 * Phase 4 chat panel: a conversational surface that streams BOTH text and
 * generative UI from the AG-UI endpoint (LangGraph router -> responder |
 * uiGenerator) over SSE.
 *
 *   - TEXT_MESSAGE_CONTENT deltas  -> append to the current assistant bubble.
 *   - CUSTOM { name: "a2ui" }      -> feed the validated A2UI messages to a
 *                                     MessageProcessor and render the resulting
 *                                     surface(s) inline in that same turn.
 *
 * A stable `threadId` is sent every turn so the server's checkpointer keeps
 * conversation memory; only the newest user message is sent. "New chat" rotates
 * the threadId and tears down rendered surfaces.
 */
import { useMemo, useRef, useState } from "react";
import { A2uiSurface } from "@a2ui/react/v0_9";
import { MessageProcessor } from "@a2ui/web_core/v0_9";
import { createPdsCatalog, CATALOG_NAME } from "./pdsCatalog";

type Role = "user" | "assistant";
interface Msg {
  role: Role;
  content: string;
  surfaceIds?: string[]; // ids of A2UI surfaces rendered in this turn
  status?: string; // transient progress note (e.g. "Generating UI…")
}

const uuid = () =>
  (crypto as any).randomUUID?.() ?? Math.random().toString(36).slice(2);
const newThreadId = () => `thread_${uuid()}`;

// Message keys that carry a surfaceId we must remap.
const SURFACE_KEYS = ["createSurface", "updateComponents", "updateDataModel", "deleteSurface"];

/**
 * Normalize incoming A2UI messages for rendering:
 *  - stamp version, point surfaces at our registered pds catalog;
 *  - REWRITE every surfaceId to `surfaceId` (a fresh id per turn). The generator
 *    always names its surface "main", so without this each new UI would reuse
 *    the same surface id and overwrite the surface object shared by every
 *    earlier assistant turn — making old bubbles render the newest UI;
 *  - apply createSurface before the messages that populate it.
 */
function normalizeA2ui(raw: any[], surfaceId: string): any[] {
  return (Array.isArray(raw) ? raw : [])
    .filter((m) => m && (m.createSurface || m.updateComponents || m.updateDataModel))
    .map((m) => {
      const out: any = { version: "v0.9", ...m };
      for (const key of SURFACE_KEYS) {
        if (out[key]?.surfaceId) out[key] = { ...out[key], surfaceId };
      }
      if (out.createSurface) out.createSurface.catalogId = CATALOG_NAME;
      return out;
    })
    .sort((a, b) => (a.createSurface ? -1 : 0) - (b.createSurface ? -1 : 0));
}

export default function Chat() {
  const [threadId, setThreadId] = useState(newThreadId);
  const [messages, setMessages] = useState<Msg[]>([]);
  const [surfacesById, setSurfacesById] = useState<Record<string, any>>({});
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  // Index of the assistant bubble for the in-flight turn, so the processor's
  // (async) onSurfaceCreated callback can attach surfaces to the right message.
  const turnRef = useRef<number>(-1);

  const scrollToBottom = () =>
    requestAnimationFrame(() => {
      const el = scrollRef.current;
      if (el) el.scrollTop = el.scrollHeight;
    });

  // One processor holding the pds catalog. Its onSurfaceCreated fires when a2ui
  // messages create a surface; we capture the surface object and link its id to
  // the current assistant turn so it renders inline.
  const processor = useMemo(() => {
    const proc = new MessageProcessor([createPdsCatalog()], (action: any) => {
      // Phase 5 will round-trip this back to the agent as a userAction. For now,
      // make event wiring observable.
      console.log("[a2ui event]", action);
    });
    proc.onSurfaceCreated((surface: any) => {
      setSurfacesById((prev) => ({ ...prev, [surface.id]: surface }));
      const idx = turnRef.current;
      setMessages((m) => {
        if (idx < 0 || idx >= m.length) return m;
        const copy = m.slice();
        const msg = copy[idx];
        const ids = new Set([...(msg.surfaceIds ?? []), surface.id]);
        copy[idx] = { ...msg, surfaceIds: [...ids] };
        return copy;
      });
      scrollToBottom();
    });
    proc.onSurfaceDeleted((surfaceId: string) => {
      setSurfacesById((prev) => {
        const next = { ...prev };
        delete next[surfaceId];
        return next;
      });
    });
    return proc;
  }, []);

  /** Render one batch of A2UI messages (from a CUSTOM a2ui event) into its own
   *  fresh surface, so it coexists with the surfaces of earlier turns. */
  const renderA2ui = (value: any) => {
    const surfaceId = `surface_${uuid()}`;
    const messagesIn = normalizeA2ui(value?.a2ui, surfaceId);
    if (messagesIn.length === 0) return;
    try {
      processor.processMessages(messagesIn);
    } catch (e: any) {
      setError(`Render error: ${e.message}`);
    }
  };

  const send = async () => {
    const text = input.trim();
    if (!text || streaming) return;

    setError(null);
    setInput("");
    // Optimistically add the user message + an empty assistant bubble to fill.
    // Record the assistant index for the surface-attach callback.
    setMessages((m) => {
      turnRef.current = m.length + 1;
      return [...m, { role: "user", content: text }, { role: "assistant", content: "" }];
    });
    setStreaming(true);
    scrollToBottom();

    // Append a text delta to the last (assistant) message.
    const appendToAssistant = (delta: string) =>
      setMessages((m) => {
        const copy = m.slice();
        const last = copy[copy.length - 1];
        if (last?.role === "assistant") copy[copy.length - 1] = { ...last, content: last.content + delta };
        return copy;
      });

    // Set the transient status note on the last (assistant) message.
    const setStatusOnAssistant = (status: string) =>
      setMessages((m) => {
        const copy = m.slice();
        const last = copy[copy.length - 1];
        if (last?.role === "assistant") copy[copy.length - 1] = { ...last, status };
        return copy;
      });

    try {
      const resp = await fetch("/agui/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          threadId,
          runId: `run_${Date.now()}`,
          messages: [{ id: `u_${Date.now()}`, role: "user", content: text }],
        }),
      });
      if (!resp.ok || !resp.body) throw new Error(`HTTP ${resp.status}`);

      // Parse the SSE stream: frames separated by a blank line, payload on `data:`.
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let sep: number;
        while ((sep = buffer.indexOf("\n\n")) !== -1) {
          const frame = buffer.slice(0, sep);
          buffer = buffer.slice(sep + 2);
          const dataLine = frame.split("\n").find((l) => l.startsWith("data:"));
          if (!dataLine) continue;
          const evt = JSON.parse(dataLine.slice(5).trim());
          if (evt.type === "TEXT_MESSAGE_CONTENT" && evt.delta) {
            appendToAssistant(evt.delta);
            scrollToBottom();
          } else if (evt.type === "CUSTOM" && evt.name === "a2ui") {
            renderA2ui(evt.value);
          } else if (evt.type === "CUSTOM" && evt.name === "status") {
            setStatusOnAssistant(evt.value?.text ?? "");
            scrollToBottom();
          } else if (evt.type === "RUN_ERROR") {
            setError(evt.message || "Run error");
          }
        }
      }
    } catch (e: any) {
      setError(`${e.message}. Is the AG-UI server running on :8090 (npm run agui)?`);
    } finally {
      setStreaming(false);
      scrollToBottom();
    }
  };

  const newChat = () => {
    // Tear down rendered surfaces before rotating the thread.
    Object.keys(surfacesById).forEach((id) => {
      try {
        processor.processMessages([{ version: "v0.9", deleteSurface: { surfaceId: id } }]);
      } catch {
        /* ignore */
      }
    });
    setSurfacesById({});
    setThreadId(newThreadId());
    setMessages([]);
    setError(null);
  };

  return (
    <div className="chat">
      <div className="chat-head">
        <span className="chat-thread">thread: {threadId.replace("thread_", "").slice(0, 8)}…</span>
        <button className="btn" onClick={newChat} disabled={streaming}>New chat</button>
      </div>

      <div className="chat-log" ref={scrollRef}>
        {messages.length === 0 && (
          <div className="empty">
            Chat, or ask for UI — e.g. “show me a sign-up form with name, email and a
            submit button”. Valid layouts render inline; anything else replies as text.
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`bubble ${m.role}${m.surfaceIds?.length ? " has-surface" : ""}`}>
            <div className="who">{m.role === "user" ? "You" : "Assistant"}</div>
            {m.content && <div className="text">{m.content}</div>}
            {m.surfaceIds?.map((id) =>
              surfacesById[id] ? (
                <div key={id} className="surface">
                  <A2uiSurface surface={surfacesById[id]} />
                </div>
              ) : null
            )}
            {!m.content && !m.surfaceIds?.length && streaming && i === messages.length - 1 && (
              <div className="text status">{m.status || "…"}</div>
            )}
          </div>
        ))}
        {error && <div className="error">{error}</div>}
      </div>

      <div className="chat-input">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") send(); }}
          placeholder="Type a message, or describe a UI…"
          disabled={streaming}
        />
        <button className="btn primary" onClick={send} disabled={streaming || !input.trim()}>
          {streaming ? "…" : "Send"}
        </button>
      </div>
    </div>
  );
}
