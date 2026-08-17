import { useMemo, useState } from "react";
import { A2uiSurface } from "@a2ui/react/v0_9";
import { MessageProcessor } from "@a2ui/web_core/v0_9";
import { createPdsCatalog, CATALOG_NAME } from "./pdsCatalog";
import Chat from "./Chat";

const SAMPLE = JSON.stringify(
  {
    a2ui: [
      {
        version: "v0.9",
        createSurface: { surfaceId: "main", catalogId: CATALOG_NAME },
      },
      {
        version: "v0.9",
        updateDataModel: {
          surfaceId: "main",
          path: "/",
          value: {
            shoes: [
              { name: "Sneaker", price: "$120" },
              { name: "Boot", price: "$150" },
              { name: "Loafer", price: "$100" },
            ],
          },
        },
      },
      {
        version: "v0.9",
        updateComponents: {
          surfaceId: "main",
          components: [
            {
              id: "root",
              component: "TileContainer",
              children: { path: "/shoes", componentId: "shoe-tile" },
            },
            {
              id: "shoe-tile",
              component: "Tilelet",
              title: { children: { path: "name" } },
              subtitle: { children: { path: "price" } },
            },
          ],
        },
      },
    ],
  },
  null,
  2
);

/** Pull the ordered A2UI messages out of whatever the user pasted. */
function extractMessages(parsed: any): any[] {
  let msgs: any[] = [];
  if (Array.isArray(parsed)) msgs = parsed;
  else if (Array.isArray(parsed?.a2ui)) msgs = parsed.a2ui;
  else if (parsed?.createSurface || parsed?.updateComponents || parsed?.updateDataModel)
    msgs = [parsed];
  else if (parsed?.result?.status?.message?.parts) {
    // Tolerate an A2A JSON-RPC envelope too.
    for (const p of parsed.result.status.message.parts) {
      if (p?.data) msgs.push(p.data);
    }
  }

  return msgs
    .filter((m) => m && (m.createSurface || m.updateComponents || m.updateDataModel))
    .map((m) => {
      const out = { version: "v0.9", ...m };
      // Point every surface at our registered pds catalog.
      if (out.createSurface) out.createSurface.catalogId = CATALOG_NAME;
      return out;
    })
    .sort((a, b) => (a.createSurface ? -1 : 0) - (b.createSurface ? -1 : 0));
}

export default function App() {
  const [text, setText] = useState(SAMPLE);
  const [error, setError] = useState<string | null>(null);
  const [surfaces, setSurfaces] = useState<any[]>([]);
  const [prompt, setPrompt] = useState("");
  const [loading, setLoading] = useState(false);
  const [tab, setTab] = useState<"ui" | "chat">("ui");

  // One processor, holding our pds catalog.
  const processor = useMemo(() => {
    // 2nd arg is the action sink: A2UI `event` actions dispatched by components
    // land here (this is where a real app would call its agent). For now, show
    // the resolved action so event wiring is observable.
    const proc = new MessageProcessor([createPdsCatalog()], (action: any) => {
      console.log("[a2ui event]", action);
      window.alert(
        `Event dispatched: ${action?.name}\ncontext: ${JSON.stringify(action?.context ?? {}, null, 2)}`
      );
    });
    proc.onSurfaceCreated((surface: any) => {
      setSurfaces((prev) => [...prev.filter((s) => s.id !== surface.id), surface]);
    });
    proc.onSurfaceDeleted((surfaceId: string) => {
      setSurfaces((prev) => prev.filter((s) => s.id !== surfaceId));
    });
    return proc;
  }, []);

  /** Tear down all known surfaces (used by the Clear button — a synchronous
   *  click, so `surfaces` state is current here). The render path clears by
   *  incoming surfaceId instead; see renderText. */
  const clearSurfaces = () => {
    surfaces.forEach((s) => {
      try {
        processor.processMessages([{ version: "v0.9", deleteSurface: { surfaceId: s.id } }]);
      } catch {
        /* ignore */
      }
    });
    setSurfaces([]);
  };

  /** Parse + render a raw JSON string. Returns true on success. */
  const renderText = (source: string): boolean => {
    setError(null);
    if (!source.trim()) {
      setError("Paste some A2UI JSON first.");
      return false;
    }
    let parsed: any;
    try {
      parsed = JSON.parse(source);
    } catch (e: any) {
      setError(`JSON parse error: ${e.message}`);
      return false;
    }
    const messages = extractMessages(parsed);
    if (messages.length === 0) {
      setError("No A2UI messages found (expected createSurface / updateComponents / updateDataModel).");
      return false;
    }
    try {
      // Drop any surface these messages will (re)create first, so re-rendering
      // the same surfaceId doesn't hit "Surface <id> already exists". Derive the
      // ids from the incoming messages, NOT from React state — the async
      // generate() flow means `surfaces` can still be stale here. The
      // processor's onSurfaceDeleted callback keeps the surface list in sync.
      const surfaceIds = new Set(
        messages
          .filter((m) => m.createSurface?.surfaceId)
          .map((m) => m.createSurface.surfaceId as string)
      );
      for (const id of surfaceIds) {
        try {
          processor.processMessages([{ version: "v0.9", deleteSurface: { surfaceId: id } }]);
        } catch {
          /* surface not present yet — nothing to delete */
        }
      }
      processor.processMessages(messages);
      return true;
    } catch (e: any) {
      setError(`Render error: ${e.message}`);
      return false;
    }
  };

  const render = () => renderText(text);

  /** Send the prompt to the /generate API, drop the result in the editor, and render it. */
  const generate = async () => {
    if (!prompt.trim()) {
      setError("Type a prompt first.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt }),
      });
      const data = await res.json();
      if (!res.ok) {
        setError(`API error (${res.status}): ${data?.error || res.statusText}${data?.hint ? `\n${data.hint}` : ""}`);
        return;
      }
      const pretty = JSON.stringify(data, null, 2);
      setText(pretty);
      renderText(pretty);
    } catch (e: any) {
      setError(`Request failed: ${e.message}. Is the server running on :8080?`);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="app">
      <header className="topbar">
        <h1>A2UI Renderer</h1>
        <span className="sub">describe a UI → generate → preview with @shadab5114/pds-core</span>
        <nav className="tabs">
          <button className={`tab ${tab === "ui" ? "active" : ""}`} onClick={() => setTab("ui")}>
            Generate UI
          </button>
          <button className={`tab ${tab === "chat" ? "active" : ""}`} onClick={() => setTab("chat")}>
            Chat
          </button>
        </nav>
      </header>

      {tab === "chat" && <Chat />}

      {tab === "ui" && (
      <>
      <div className="promptbar">
        <input
          className="prompt-input"
          type="text"
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !loading) generate(); }}
          placeholder="Describe the UI you want (e.g. “a sign-up form with name, email and a submit button”)…"
          disabled={loading}
        />
        <button className="btn primary" onClick={generate} disabled={loading}>
          {loading ? "Generating…" : "Generate ✦"}
        </button>
      </div>

      <div className="split">
        <section className="pane left">
          <div className="pane-head">
            <h2>A2UI JSON</h2>
            <div className="actions">
              <button className="btn primary" onClick={render}>
                Render ▶
              </button>
              <button className="btn" onClick={() => { setText(""); clearSurfaces(); setError(null); }}>
                Clear
              </button>
              <button className="btn" onClick={() => setText(SAMPLE)}>
                Load sample
              </button>
            </div>
          </div>
          <textarea
            className="editor"
            spellCheck={false}
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Paste the A2UI JSON generated by your server (or any A2UI v0.9 JSON)…"
          />
          {error && <div className="error">{error}</div>}
        </section>

        <section className="pane right">
          <div className="pane-head">
            <h2>Preview</h2>
          </div>
          <div className="preview">
            {surfaces.length === 0 && (
              <div className="empty">Nothing rendered yet — paste JSON and hit <b>Render</b>.</div>
            )}
            {surfaces.map((surface) => (
              <div key={surface.id} className="surface">
                <A2uiSurface surface={surface} />
              </div>
            ))}
          </div>
        </section>
      </div>
      </>
      )}
    </div>
  );
}
