#!/usr/bin/env node
/**
 * Summarise the @shadab5114/pds-core component catalog installed in the
 * current working repo.
 *
 * Usage: node list-components.mjs             # all components, compact prop summary
 *        node list-components.mjs <Name>      # full JSON schema for one component
 */
import { createRequire } from "node:module";
import path from "node:path";

const req = createRequire(path.join(process.cwd(), "package.json"));
let catalog;
try {
  catalog = req("@shadab5114/pds-core/catalog.json");
} catch {
  console.error(
    `Cannot resolve @shadab5114/pds-core/catalog.json from ${process.cwd()}.\n` +
      "Run this inside the repo where @shadab5114/pds-core is installed."
  );
  process.exit(1);
}

const comps = catalog.components ?? {};
const only = process.argv[2];

if (only) {
  const c = comps[only];
  if (!c) {
    console.error(`No component "${only}". Available: ${Object.keys(comps).join(", ")}`);
    process.exit(1);
  }
  console.log(JSON.stringify(c, null, 2));
  process.exit(0);
}

function propLine(name, schema, required) {
  let t;
  if (schema.enum) t = schema.enum.join("|");
  else if (schema.$ref) t = schema.$ref.split("/").pop();
  else if (schema.const !== undefined) t = JSON.stringify(schema.const);
  else t = schema.type ?? "any";
  const def = schema.default !== undefined ? `=${JSON.stringify(schema.default)}` : "";
  return `${name}${required ? "*" : ""}:${t}${def}`;
}

console.log(`catalogId: ${catalog.catalogId ?? catalog.$id ?? "(none)"}\n`);
for (const [name, def] of Object.entries(comps)) {
  const parts = def.allOf ?? [def];
  const properties = {};
  const required = new Set();
  for (const p of parts) {
    Object.assign(properties, p.properties ?? {});
    for (const r of p.required ?? []) required.add(r);
  }
  delete properties.component;
  required.delete("component");
  const props = Object.entries(properties).map(([k, v]) => propLine(k, v, required.has(k)));
  console.log(`${name} — ${def.description ?? ""}`);
  console.log(`  ${props.join(", ") || "(no props)"}\n`);
}
