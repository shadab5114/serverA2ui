import "dotenv/config";
import express from "express";
import { fetchCatalog } from "./mcpClient.js";
import { buildSystemPrompt } from "./systemPrompt.js";
import { generateA2UI } from "./llm.js";

const app = express();
app.use(express.json({ limit: "1mb" }));

const PORT = process.env.PORT || 8080;

// Health check.
app.get("/health", (_req, res) => {
  res.json({ status: "ok", provider: process.env.LLM_PROVIDER || "openai" });
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
  const prompt = req.body?.prompt;
  if (!prompt || typeof prompt !== "string") {
    return res
      .status(400)
      .json({ error: 'Request body must include a non-empty "prompt" string.' });
  }

  try {
    // 1. Full component schemas are sourced live from the MCP server every request.
    const catalog = await fetchCatalog();

    // 2 + 3. Build prompt and generate.
    const systemPrompt = buildSystemPrompt(catalog);
    const { json, provider, model } = await generateA2UI(systemPrompt, prompt);

    // 4. Return the A2UI document plus a little metadata.
    return res.json({
      meta: {
        provider,
        model,
        catalogId: catalog.catalogId,
        components: catalog.names,
        generatedAt: new Date().toISOString(),
      },
      ...json,
    });
  } catch (err) {
    console.error("[/generate] error:", err);
    const isMcp = /MCP|catalog|tool/i.test(err.message || "");
    return res.status(isMcp ? 502 : 500).json({
      error: err.message || "Internal error",
      hint: isMcp
        ? "Could not get the catalog from the MCP server. Is it running at MCP_URL?"
        : undefined,
    });
  }
});

app.listen(PORT, () => {
  console.log(`A2UI server listening on http://localhost:${PORT}`);
  console.log(`  POST /generate   { "prompt": "..." }`);
  console.log(`  GET  /health`);
  console.log(`  LLM provider: ${process.env.LLM_PROVIDER || "openai"}`);
  console.log(`  MCP catalog:  ${process.env.MCP_URL || "http://localhost:3939/mcp"}`);
});
