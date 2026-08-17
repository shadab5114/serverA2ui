// Readable, dependency-free server logging.
//
// Goal: a clear, human-readable trace of how a request flows through the
// pipeline and what response goes back — NOT machine JSON dumps. Each request
// gets a short id and per-step timings so concurrent requests stay legible.

const useColor = process.stdout.isTTY && !process.env.NO_COLOR;
const paint = (code, s) => (useColor ? `\x1b[${code}m${s}\x1b[0m` : s);

const c = {
  dim: (s) => paint("90", s),
  cyan: (s) => paint("36", s),
  green: (s) => paint("32", s),
  yellow: (s) => paint("33", s),
  red: (s) => paint("31", s),
  bold: (s) => paint("1", s),
};

const stamp = () => new Date().toISOString().slice(11, 23); // HH:MM:SS.mmm

let counter = 0;
const nextId = () => (++counter).toString(36).padStart(3, "0");

/**
 * Create a per-request logger.
 * @param {string} tag  short label for the route, e.g. "/generate"
 */
export function requestLogger(tag) {
  const id = nextId();
  const t0 = performance.now();
  let last = t0;

  const prefix = () => `${c.dim(stamp())} ${c.cyan(tag)} ${c.dim("#" + id)}`;
  const total = () => `${(performance.now() - t0).toFixed(0)}ms`;
  const lap = () => {
    const now = performance.now();
    const d = now - last;
    last = now;
    return c.dim(`+${d.toFixed(0)}ms`);
  };

  return {
    id,
    /** Start of a request. */
    start: (msg) => console.log(`${prefix()} ${c.bold("▶")}  ${msg}`),
    /** An intermediate step (shows time since the previous step). */
    step: (msg) => console.log(`${prefix()} ${c.dim("│")}  ${msg}  ${lap()}`),
    /** A non-fatal warning within the flow. */
    warn: (msg) => console.warn(`${prefix()} ${c.yellow("│  ⚠")}  ${msg}  ${lap()}`),
    /** Successful completion (shows total elapsed). */
    done: (msg) => console.log(`${prefix()} ${c.green("└▶")} ${msg}  ${c.dim("(" + total() + " total)")}`),
    /** Failed completion (shows total elapsed). */
    fail: (msg) => console.error(`${prefix()} ${c.red("└✗")} ${msg}  ${c.dim("(" + total() + " total)")}`),
  };
}

/**
 * Summarize an A2UI document into readable fragments (no JSON dumps).
 * @returns {{ messageCount:number, flow:string, componentCount:number, breakdown:string }}
 */
export function summarizeA2UI(json) {
  const msgs = Array.isArray(json?.a2ui) ? json.a2ui : [];
  const flow = msgs
    .map((m) => Object.keys(m).find((k) => k !== "version") || "?")
    .join(" → ");

  const comps = msgs.find((m) => m?.updateComponents)?.updateComponents?.components || [];
  const counts = new Map();
  for (const node of comps) {
    const name = node?.component || "?";
    counts.set(name, (counts.get(name) || 0) + 1);
  }
  const breakdown = [...counts.entries()]
    .map(([name, n]) => (n > 1 ? `${name}×${n}` : name))
    .join(", ");

  return {
    messageCount: msgs.length,
    flow: flow || "(none)",
    componentCount: comps.length,
    breakdown: breakdown || "(none)",
  };
}
