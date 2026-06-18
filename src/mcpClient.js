import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";

const MCP_URL = process.env.MCP_URL || "http://localhost:3939/mcp";

/**
 * Fetch the full component catalog from the MCP server at runtime.
 *
 * Two-step, live on every call:
 *   1. list_component_catalog  -> thin list (catalogId + component names)
 *   2. get_component_schema    -> full A2UI schema for every component,
 *                                 bundled with the $defs they reference.
 *
 * A fresh connection is opened and closed each call so the catalog is always
 * sourced live from the MCP server.
 *
 * @returns {Promise<{catalogId: string, components: object, defs: object, names: string[]}>}
 */
export async function fetchCatalog() {
  const client = new Client(
    { name: "a2ui-llm-server", version: "1.0.0" },
    { capabilities: {} }
  );
  const transport = new StreamableHTTPClientTransport(new URL(MCP_URL));

  try {
    try {
      await client.connect(transport);
    } catch (err) {
      throw new Error(`Failed to connect to MCP server at ${MCP_URL}: ${err.message}`);
    }

    const { tools } = await client.listTools();
    const toolNames = new Set((tools || []).map((t) => t.name));

    const listTool = pick(toolNames, ["list_component_catalog"], /catalog/i);
    if (!listTool) {
      throw new Error(
        `No catalog tool found. Available: ${[...toolNames].join(", ")}`
      );
    }

    // 1. Thin catalog: names + catalogId.
    const thinRaw = await callText(client, listTool, {});
    const thin = JSON.parse(thinRaw);
    const catalogId = thin.catalogId || "";
    const names = (thin.components || [])
      .map((c) => c.name)
      .filter(Boolean);

    if (names.length === 0) {
      throw new Error(`Catalog tool "${listTool}" returned no components.`);
    }

    // 2. Full schemas (bundled with referenced $defs) for every component.
    const schemaTool = pick(toolNames, ["get_component_schema"], /schema/i);
    if (!schemaTool) {
      // Degrade gracefully: hand back the thin list as "components".
      const components = Object.fromEntries(
        (thin.components || []).map((c) => [c.name, { description: c.description }])
      );
      return { catalogId, components, defs: {}, names };
    }

    const fullRaw = await callText(client, schemaTool, { components: names });
    const full = JSON.parse(fullRaw);

    return {
      catalogId,
      components: full.components || {},
      defs: full.$defs || {},
      names,
    };
  } finally {
    await client.close().catch(() => {});
  }
}

function pick(toolNames, preferred, pattern) {
  for (const name of preferred) if (toolNames.has(name)) return name;
  for (const name of toolNames) if (pattern.test(name)) return name;
  return null;
}

async function callText(client, name, args) {
  const result = await client.callTool({ name, arguments: args });
  if (Array.isArray(result?.content)) {
    const text = result.content
      .filter((c) => c.type === "text" && typeof c.text === "string")
      .map((c) => c.text)
      .join("\n")
      .trim();
    if (text) return text;
  }
  if (result?.structuredContent) return JSON.stringify(result.structuredContent);
  throw new Error(`Tool "${name}" returned no text content.`);
}
