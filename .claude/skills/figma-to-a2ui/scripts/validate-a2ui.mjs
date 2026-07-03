#!/usr/bin/env node
/**
 * Structural validation of an A2UI v0.9 payload against the envelope rules and
 * the @shadab5114/pds-core catalog installed in the current working repo.
 *
 * Usage: node validate-a2ui.mjs <payload.json>
 * Exits non-zero if any ERROR is found.
 */
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";

const file = process.argv[2];
if (!file) {
  console.error("usage: node validate-a2ui.mjs <payload.json>");
  process.exit(1);
}

let catalogComponents = null;
try {
  const req = createRequire(path.join(process.cwd(), "package.json"));
  const catalog = req("@shadab5114/pds-core/catalog.json");
  catalogComponents = new Set(Object.keys(catalog.components ?? {}));
} catch {
  console.warn("WARN: could not resolve @shadab5114/pds-core/catalog.json — skipping component-type checks");
}

const errors = [];
const warns = [];
const err = (m) => errors.push(m);
const warn = (m) => warns.push(m);

const payload = JSON.parse(fs.readFileSync(file, "utf8"));
const MESSAGE_KEYS = ["createSurface", "updateDataModel", "updateComponents", "deleteSurface"];

if (!Array.isArray(payload.a2ui)) {
  err('top level must be { "a2ui": [ ...messages ] }');
} else {
  payload.a2ui.forEach((msg, i) => {
    const where = `message[${i}]`;
    if (msg.version !== "v0.9") err(`${where}: version must be "v0.9"`);
    const keys = Object.keys(msg).filter((k) => k !== "version");
    if (keys.length !== 1 || !MESSAGE_KEYS.includes(keys[0])) {
      err(`${where}: must have exactly one of ${MESSAGE_KEYS.join("/")} (got: ${keys.join(", ") || "none"})`);
      return;
    }
    const kind = keys[0];
    const body = msg[kind];
    if (!body?.surfaceId) err(`${where}: ${kind}.surfaceId is required`);

    if (kind === "createSurface") {
      if (!body.catalogId) err(`${where}: createSurface.catalogId is required`);
      if ("root" in body) err(`${where}: createSurface has no "root" field in v0.9`);
    }
    if (kind === "updateDataModel") {
      if (typeof body.path !== "string" || !body.path.startsWith("/"))
        err(`${where}: updateDataModel.path must be a JSON Pointer starting with "/"`);
      if ("contents" in body) err(`${where}: use "value", not "contents"`);
      if (!("value" in body)) err(`${where}: updateDataModel.value is required`);
    }
    if (kind === "updateComponents") {
      const comps = body.components;
      if (!Array.isArray(comps)) {
        err(`${where}: updateComponents.components must be an array`);
        return;
      }
      const ids = new Set();
      for (const c of comps) {
        if (!c.id) err(`${where}: component missing "id"`);
        else if (ids.has(c.id)) err(`${where}: duplicate component id "${c.id}"`);
        else ids.add(c.id);
        if (!c.component) err(`${where}: component "${c.id}" missing "component" type name`);
        else if (catalogComponents && !catalogComponents.has(c.component))
          err(`${where}: "${c.id}" uses unknown component "${c.component}" (not in catalog)`);
        for (const bad of ["componentType", "properties", "bindings"])
          if (bad in c) err(`${where}: "${c.id}" uses "${bad}" wrapper — props go inline`);
      }
      if (!ids.has("root")) err(`${where}: exactly one component must have id "root"`);

      // Collect child references anywhere in props: arrays of ids under "children",
      // and list templates { path, componentId }.
      const refs = [];
      const scan = (v) => {
        if (Array.isArray(v)) return v.forEach(scan);
        if (v && typeof v === "object") {
          if (typeof v.componentId === "string") refs.push(v.componentId);
          for (const [k, val] of Object.entries(v)) {
            if (k === "children" && Array.isArray(val) && val.every((x) => typeof x === "string"))
              refs.push(...val);
            else scan(val);
          }
          if (typeof v.path === "string" && v.path.includes(".") && !v.path.startsWith("/"))
            warn(`path "${v.path}" looks like dot notation — bindings must be JSON Pointers`);
        }
      };
      comps.forEach(scan);
      for (const r of refs)
        if (!ids.has(r)) err(`${where}: child reference "${r}" has no matching component id`);
      const referenced = new Set(refs);
      for (const id of ids)
        if (id !== "root" && !referenced.has(id))
          warn(`${where}: component "${id}" is never referenced as a child`);
    }
  });
}

for (const w of warns) console.log("WARN: " + w);
for (const e of errors) console.log("ERROR: " + e);
console.log(errors.length ? `\n${errors.length} error(s).` : "OK — structurally valid.");
process.exit(errors.length ? 1 : 0);
