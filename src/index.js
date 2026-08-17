import "dotenv/config";
import express from "express";
import { fetchCatalog } from "./mcpClient.js";
import { loadLocalCatalog } from "./localCatalog.js";
import { buildSystemPrompt } from "./systemPrompt.js";
import { generateA2UI } from "./llm.js";
import { validateAndRepairGraph } from "./validateGraph.js";
import { validateA2UIDocument } from "./catalogSchemas.js";
import { mergeBasicLayout } from "./basicLayoutCatalog.js";
import { requestLogger, summarizeA2UI } from "./logger.js";

/** One-line, log-safe preview of the prompt (single line, truncated). */
const preview = (s, n = 70) => {
  const flat = String(s).replace(/\s+/g, " ").trim();
  return flat.length > n ? `${flat.slice(0, n)}…` : flat;
};

// Catalog source: local committed catalog.json by default (no external
// dependency), or the live MCP server when CATALOG_SOURCE=mcp. See
// A2UI-BACKEND-ARCHITECTURE.md §1 — catalog.json is the single source of truth.
const CATALOG_SOURCE = (process.env.CATALOG_SOURCE || "local").toLowerCase();
const getCatalog = CATALOG_SOURCE === "mcp" ? fetchCatalog : loadLocalCatalog;

const app = express();
app.use(express.json({ limit: "1mb" }));

const PORT = process.env.PORT || 8080;

// Health check.
app.get("/health", (_req, res) => {
  res.json({
    status: "ok",
    provider: process.env.LLM_PROVIDER || "openai",
    catalogSource: CATALOG_SOURCE,
  });
});

/**
 * POST /generate
 * Body: { "prompt": "build a login form with email and password" }
 *
 * Flow (every request):
 *   1. Fetch the component catalog LIVE from the MCP server.
 *   2. Build the A2UI system prompt embedding that catalog.
 *   3. Ask the LLM to produce A2UI JSON.
 *   4. Return the A2UI JSON.
 */
app.post("/generate", async (req, res) => {
  const log = requestLogger("/generate");
  const prompt = req.body?.prompt;
  if (!prompt || typeof prompt !== "string") {
    log.start("rejected — missing/invalid prompt");
    log.fail("400 Bad Request");
    return res
      .status(400)
      .json({ error: 'Request body must include a non-empty "prompt" string.' });
  }

  log.start(`prompt "${preview(prompt)}" (${prompt.length} chars)`);

  try {
    // 1. Full component schemas — from the local catalog.json by default, or the
    //    live MCP server when CATALOG_SOURCE=mcp.
    const catalog = await getCatalog();
    const pdsCount = catalog.names.length;
    log.step(`catalog loaded — source=${CATALOG_SOURCE}, ${pdsCount} components`);

    // 1b. Merge borrowed layout components (Column/Row/List/Divider) from the
    //     basic catalog — the design system has no generic container. The DS
    //     wins on any name collision. The client registers matching renderers.
    mergeBasicLayout(catalog);
    log.step(`layout merged — +${catalog.names.length - pdsCount} fallback containers → ${catalog.names.length} total`);

    // 2. Build the system prompt embedding the catalog.
    const systemPrompt = buildSystemPrompt(catalog);
    log.step(`system prompt built — ${systemPrompt.length.toLocaleString()} chars`);

    // 3. Ask the LLM to produce A2UI JSON.
    log.step(`calling LLM — provider=${process.env.LLM_PROVIDER || "openai"}…`);
    const { json, provider, model } = await generateA2UI(systemPrompt, prompt);
    const a2ui = summarizeA2UI(json);
    log.step(`LLM responded — ${provider}/${model}, ${a2ui.messageCount} messages: ${a2ui.flow}`);

    // 3b. Sanity-check the component graph and repair orphans so the UI is not
    //     silently blank when the model mis-wires children.
    const validation = validateAndRepairGraph(json);
    if (validation.errors.length) {
      log.warn(`graph check — ${validation.errors.length} error(s): ${validation.errors.join("; ")}`);
    } else if (validation.repaired || validation.warnings.length) {
      log.warn(`graph check — ${validation.repaired ? "repaired" : "ok"}, ${validation.warnings.length} warning(s)`);
    } else {
      log.step("graph check — ok, no repairs");
    }

    // 3c. Validate every component's props against the design system's shipped
    //     Zod schemas. NON-BLOCKING in Phase 2 (surfaced in meta for visibility);
    //     Phase 4 turns this into a hard gate + repair loop.
    const schemaValidation = validateA2UIDocument(json);
    const skipped = schemaValidation.unknownComponents.length
      ? ` (skipped non-pds: ${schemaValidation.unknownComponents.join(", ")})`
      : "";
    if (schemaValidation.valid) {
      log.step(`schema check — ${schemaValidation.checked}/${schemaValidation.checked} valid${skipped}`);
    } else {
      const detail = schemaValidation.failures
        .map((f) => `${f.id}(${f.component}): ${f.issues.join(", ")}`)
        .join(" | ");
      log.warn(`schema check — ${schemaValidation.failures.length} failure(s): ${detail}`);
    }

    // 4. Return the A2UI document plus a little metadata.
    log.done(`200 — ${a2ui.componentCount} components [${a2ui.breakdown}]`);
    return res.json({
      meta: {
        provider,
        model,
        catalogId: catalog.catalogId,
        components: catalog.names,
        generatedAt: new Date().toISOString(),
        validation,
        schemaValidation,
      },
      ...json,
    });
  } catch (err) {
    const isCatalog = /MCP|catalog|tool/i.test(err.message || "");
    log.fail(`${isCatalog ? "502" : "500"} — ${err.message || "Internal error"}`);
    // Unexpected (non-catalog) errors: print the stack for debugging (not JSON).
    if (!isCatalog && err.stack) console.error(err.stack);
    const hint = isCatalog
      ? CATALOG_SOURCE === "mcp"
        ? "Could not get the catalog from the MCP server. Is it running at MCP_URL?"
        : "Could not read the local catalog.json. Check LOCAL_CATALOG_PATH / outsource/catalog.json."
      : undefined;
    return res.status(isCatalog ? 502 : 500).json({
      error: err.message || "Internal error",
      hint,
    });
  }
});

app.listen(PORT, () => {
  console.log(`A2UI server listening on http://localhost:${PORT}`);
  console.log(`  POST /generate   { "prompt": "..." }`);
  console.log(`  GET  /health`);
  console.log(`  LLM provider: ${process.env.LLM_PROVIDER || "openai"}`);
  console.log(
    `  Catalog:      ${CATALOG_SOURCE === "mcp" ? `MCP ${process.env.MCP_URL || "http://localhost:3939/mcp"}` : process.env.LOCAL_CATALOG_PATH || "local @shadab5114/pds-core/catalog.json"}`
  );
});
