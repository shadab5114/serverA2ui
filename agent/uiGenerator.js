// Phase 4 — the generative-UI core: the validator GATE + repair loop.
//
// This is the "nothing reaches the wire until it validates" boundary from
// A2UI-BACKEND-ARCHITECTURE.md §1. It reuses the exact same generation pipeline
// as the standalone /generate server (src/*), but wraps it in a bounded repair
// loop so the graph's UI branch either returns a catalog-valid A2UI document or
// reports a clean failure the caller can degrade to text.
//
//   generateA2UI ─▶ validateAndRepairGraph (orphans) ─▶ validateA2UIDocument (zod gate)
//        ▲                                                      │
//        └────────── repair prompt (prev JSON + errors) ◀───────┘  (max 2 retries)
//
// On success: { ok: true, a2ui, meta }. On exhaustion: { ok: false, errors, ... }
// so the graph node can fall back to a plain-text apology instead of crashing.

import { loadLocalCatalog } from "../src/localCatalog.js";
import { mergeBasicLayout } from "../src/basicLayoutCatalog.js";
import { buildSystemPrompt } from "../src/systemPrompt.js";
import { generateA2UI } from "../src/llm.js";
import { validateAndRepairGraph } from "../src/validateGraph.js";
import { validateA2UIDocument } from "../src/catalogSchemas.js";

const MAX_REPAIRS = Number(process.env.A2UI_MAX_REPAIRS) || 2;

// The system prompt embeds the whole catalog, so build it once and reuse it
// across turns (the catalog is cached in loadLocalCatalog too).
let systemPromptCache = null;
async function getSystemPrompt() {
  if (systemPromptCache) return systemPromptCache;
  const catalog = await loadLocalCatalog();
  mergeBasicLayout(catalog); // Column/Row/List/Divider fallback containers
  systemPromptCache = buildSystemPrompt(catalog);
  return systemPromptCache;
}

/** Flatten schema + graph failures into short lines the model can act on. */
function collectErrors(graphValidation, schemaValidation) {
  const errors = [];
  for (const e of graphValidation.errors) errors.push(e);
  for (const f of schemaValidation.failures) {
    errors.push(`Component "${f.id}" (${f.component}): ${f.issues.join("; ")}`);
  }
  return errors;
}

/** Build the retry prompt: original ask + the rejected JSON + the exact errors. */
function buildRepairPrompt(userPrompt, rejectedDoc, errors) {
  return (
    `${userPrompt}\n\n` +
    `Your previous A2UI JSON was REJECTED by the validator. Fix ONLY these ` +
    `errors and return the corrected, complete JSON object (same output ` +
    `contract — a single { "a2ui": [...] } object, no prose):\n\n` +
    `Errors:\n${errors.map((e) => `- ${e}`).join("\n")}\n\n` +
    `Previous (invalid) JSON:\n${JSON.stringify(rejectedDoc)}`
  );
}

/**
 * Generate an A2UI document for a natural-language prompt and only return it if
 * it passes the validator gate; otherwise repair (bounded) and, failing that,
 * report the errors so the caller can fall back to text.
 *
 * @param {string} userPrompt
 * @param {{ maxRepairs?: number, log?: { step: Function, warn: Function } }} [opts]
 * @returns {Promise<
 *   | { ok: true,  a2ui: object, meta: object, attempts: number }
 *   | { ok: false, errors: string[], attempts: number, lastDoc: object|null }
 * >}
 */
export async function generateValidatedA2UI(userPrompt, opts = {}) {
  const maxRepairs = opts.maxRepairs ?? MAX_REPAIRS;
  const log = opts.log;
  const systemPrompt = await getSystemPrompt();

  let promptForModel = userPrompt;
  let lastDoc = null;
  let lastErrors = [];
  let provider;
  let model;

  for (let attempt = 0; attempt <= maxRepairs; attempt++) {
    const res = await generateA2UI(systemPrompt, promptForModel);
    provider = res.provider;
    model = res.model;
    const doc = res.json;
    lastDoc = doc;

    // Auto-repair orphans/root wiring first (mutates doc), then hard-gate on the
    // design system's shipped zod schemas.
    const graphValidation = validateAndRepairGraph(doc);
    const schemaValidation = validateA2UIDocument(doc);

    const errors = collectErrors(graphValidation, schemaValidation);
    if (errors.length === 0) {
      log?.step(
        `UI valid on attempt ${attempt + 1}/${maxRepairs + 1}` +
          (graphValidation.repaired ? " (graph auto-repaired)" : "")
      );
      return {
        ok: true,
        a2ui: doc,
        attempts: attempt + 1,
        meta: {
          provider,
          model,
          attempts: attempt + 1,
          graphRepaired: graphValidation.repaired,
          schemaChecked: schemaValidation.checked,
          unknownComponents: schemaValidation.unknownComponents,
        },
      };
    }

    lastErrors = errors;
    log?.warn(
      `UI attempt ${attempt + 1}/${maxRepairs + 1} rejected — ${errors.length} error(s): ${errors.join(" | ")}`
    );
    if (attempt < maxRepairs) promptForModel = buildRepairPrompt(userPrompt, doc, errors);
  }

  return { ok: false, errors: lastErrors, attempts: maxRepairs + 1, lastDoc };
}
