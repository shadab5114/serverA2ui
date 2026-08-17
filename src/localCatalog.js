import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);

// Single source of truth: the catalog.json that ships INSIDE @shadab5114/pds-core
// (kept in lockstep with the design system's zod schemas — see ./catalogSchemas.js).
// This is the 35-component current catalog, not the stale outsource/ copy.
// Override with LOCAL_CATALOG_PATH to point at a different catalog file.
const CATALOG_OVERRIDE = process.env.LOCAL_CATALOG_PATH || null;

let cache = null;

/**
 * Load the component catalog and shape it exactly like {@link fetchCatalog} from
 * ./mcpClient.js so the rest of the pipeline (systemPrompt, mergeBasicLayout,
 * meta) is unchanged:
 *
 *   { catalogId, components, defs, names }
 *
 * By default the catalog is read from the installed @shadab5114/pds-core package
 * (offline, no MCP server). It is cached — the catalog does not change between
 * requests.
 *
 * @returns {Promise<{catalogId: string, components: object, defs: object, names: string[]}>}
 */
export async function loadLocalCatalog() {
  if (cache) return cache;

  let doc;
  if (CATALOG_OVERRIDE) {
    let raw;
    try {
      raw = await readFile(CATALOG_OVERRIDE, "utf8");
    } catch (err) {
      throw new Error(`Failed to read local catalog at ${CATALOG_OVERRIDE}: ${err.message}`);
    }
    try {
      doc = JSON.parse(raw);
    } catch (err) {
      throw new Error(`Local catalog at ${CATALOG_OVERRIDE} is not valid JSON: ${err.message}`);
    }
  } else {
    try {
      doc = require("@shadab5114/pds-core/catalog.json");
    } catch (err) {
      throw new Error(
        `Failed to load @shadab5114/pds-core/catalog.json: ${err.message}. ` +
          `Is the package installed? (npm install)`
      );
    }
  }

  const components = doc.components || {};
  const names = Object.keys(components);
  if (names.length === 0) {
    throw new Error("Loaded catalog has no components.");
  }

  cache = {
    catalogId: doc.catalogId || doc.$id || "",
    components,
    defs: doc.$defs || {},
    names,
  };
  return cache;
}

/** Clear the in-memory cache (used by tests / hot-reload). */
export function clearCatalogCache() {
  cache = null;
}
