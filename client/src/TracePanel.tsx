/**
 * Trace panel (P7): what the agent did for one assistant turn, from standard
 * AG-UI events.
 *
 *   STEP_STARTED / STEP_FINISHED                    -> the phases (decide, ground, build)
 *   TOOL_CALL_START / ARGS / END / RESULT           -> each traced call: the decision,
 *       guideline and MCP queries (with their sources), data providers, the design
 *       brief, every generation attempt and the guideline checks.
 *
 * The server puts a short human `summary` in every tool result, plus details
 * (`sources`, `brief`, `violations`, …) shown on demand.
 */
import { useState } from "react";

export type TraceItem =
  | { kind: "step"; name: string; done: boolean }
  | { kind: "tool"; id: string; name: string; args?: any; result?: any; done: boolean };

const safeJson = (s: string) => {
  try {
    return JSON.parse(s);
  } catch {
    return s;
  }
};

/** Fold one AG-UI event into a turn's trace. Returns the same array when the event isn't a trace event. */
export function applyTraceEvent(trace: TraceItem[], evt: any): TraceItem[] {
  switch (evt.type) {
    case "STEP_STARTED":
      return [...trace, { kind: "step", name: evt.stepName, done: false }];
    case "STEP_FINISHED":
      return trace.map((t) => (t.kind === "step" && t.name === evt.stepName && !t.done ? { ...t, done: true } : t));
    case "TOOL_CALL_START":
      return [...trace, { kind: "tool", id: evt.toolCallId, name: evt.toolCallName, done: false }];
    case "TOOL_CALL_ARGS":
      return trace.map((t) => (t.kind === "tool" && t.id === evt.toolCallId ? { ...t, args: safeJson(evt.delta) } : t));
    case "TOOL_CALL_RESULT":
      return trace.map((t) =>
        t.kind === "tool" && t.id === evt.toolCallId ? { ...t, result: safeJson(evt.content), done: true } : t
      );
    default:
      return trace;
  }
}

export const isTraceEvent = (evt: any) =>
  ["STEP_STARTED", "STEP_FINISHED", "TOOL_CALL_START", "TOOL_CALL_ARGS", "TOOL_CALL_RESULT"].includes(evt?.type);

function Sources({ sources }: { sources: any[] }) {
  return (
    <ul className="trace-sources">
      {sources.map((s) => (
        <li key={s.id} title={s.text}>
          <span className="trace-cite">{s.id}</span> {s.title}
          {s.origin && <span className="trace-origin"> · {s.origin}</span>}
        </li>
      ))}
    </ul>
  );
}

function ToolRow({ item }: { item: Extract<TraceItem, { kind: "tool" }> }) {
  const [open, setOpen] = useState(false);
  const r = item.result ?? {};
  const sources: any[] = Array.isArray(r.sources) ? r.sources : [];
  const failed = typeof r.summary === "string" && (r.error || /violation|rejected|issue\(s\)/.test(r.summary));
  return (
    <li className={`trace-tool${item.done ? "" : " running"}${failed ? " flagged" : ""}`}>
      <button className="trace-toggle" onClick={() => setOpen(!open)} aria-expanded={open}>
        <code>{item.name}</code>
        <span className="trace-summary">{item.done ? r.summary ?? "done" : "running…"}</span>
      </button>
      {r.note && <div className="trace-note">{r.note}</div>}
      {sources.length > 0 && <Sources sources={sources} />}
      {open && (
        <pre className="trace-json">{JSON.stringify({ args: item.args, result: item.result }, null, 2)}</pre>
      )}
    </li>
  );
}

export default function TracePanel({ trace, live }: { trace: TraceItem[]; live: boolean }) {
  if (!trace.length) return null;
  const steps = trace.filter((t) => t.kind === "step").map((t) => t.name);
  const calls = trace.filter((t) => t.kind === "tool").length;
  return (
    <details className="trace" open={live || undefined}>
      <summary>
        Trace · {steps.join(" → ") || "—"} · {calls} call{calls === 1 ? "" : "s"}
      </summary>
      <ol className="trace-list">
        {trace.map((t, i) =>
          t.kind === "step" ? (
            <li key={`s${i}`} className="trace-step">
              {t.name}
            </li>
          ) : (
            <ToolRow key={t.id} item={t} />
          )
        )}
      </ol>
    </details>
  );
}
