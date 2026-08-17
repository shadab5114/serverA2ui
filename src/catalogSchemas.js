// Validate generated A2UI components against the Zod v4 schemas that ship with
// @shadab5114/pds-core (auto-generated from the same catalog.json — see the
// package's scripts/generate-catalog.mjs). This is the "validator" side of
// A2UI-BACKEND-ARCHITECTURE.md §1: the design system's schemas are the single
// source of truth, so we consume them rather than re-deriving Zod from JSON
// Schema ourselves.
//
// Phase 2 uses this as a NON-BLOCKING check (warnings only). Phase 4 turns it
// into a hard validator gate feeding a repair loop.

import * as pdsSchemas from "@shadab5114/pds-core/schemas";

// component name -> its props schema (e.g. "Button" -> ButtonSchema).
const SCHEMA_BY_COMPONENT = new Map();
for (const [exportName, schema] of Object.entries(pdsSchemas)) {
  const m = /^(.+)Schema$/.exec(exportName);
  if (m && schema && typeof schema.safeParse === "function") {
    SCHEMA_BY_COMPONENT.set(m[1], schema);
  }
}

/** Component names the design system knows how to validate. */
export const KNOWN_COMPONENTS = [...SCHEMA_BY_COMPONENT.keys()];

// Common-wrapper keys that live on every component but are NOT part of a
// component's own props schema. NOTE: `children`/`child` are deliberately NOT
// here — for containers they are child refs, but for many components (Button,
// Text, TextLink…) `children` is a real, often required prop (the label). The
// pds schemas are non-strict, so leftover keys the schema doesn't know (e.g.
// `action`, `checks`, or `children` on a container) are ignored, not rejected.
const WRAPPER_KEYS = new Set(["id", "component", "weight"]);

/** An A2UI DataBinding ({ path }) or list template ({ path, componentId }). */
function isBinding(v) {
  return v != null && typeof v === "object" && typeof v.path === "string";
}

/** Read the value at a zod issue path (array of keys/indices) from an object. */
function valueAtPath(obj, path) {
  let cur = obj;
  for (const key of path) {
    if (cur == null || typeof cur !== "object") return undefined;
    cur = cur[key];
  }
  return cur;
}

/**
 * Validate one A2UI component object against its pds props schema.
 *
 * Binding-aware: the pds schemas describe STATIC prop types (e.g. value:
 * z.string()), but in A2UI most props may instead be a DataBinding
 * ({ path: "/..." }) resolved at render time. A type error whose offending
 * value is a binding is therefore NOT a real error and is ignored.
 *
 * @returns {{ ok: boolean, component: string, id: string, issues: string[], unknown: boolean }}
 */
export function validateComponent(node) {
  const id = node?.id ?? "<no id>";
  const component = node?.component;
  if (!component || typeof component !== "string") {
    return { ok: false, component: String(component), id, unknown: false, issues: ["missing 'component' name"] };
  }

  const schema = SCHEMA_BY_COMPONENT.get(component);
  if (!schema) {
    // Not a pds component (e.g. borrowed layout Column/Row/List/Divider) — we
    // can't validate it here, but it's not necessarily invalid.
    return { ok: true, component, id, unknown: true, issues: [] };
  }

  // Strip wrapper keys the props schema doesn't describe, then parse the rest.
  const props = {};
  for (const [k, v] of Object.entries(node)) {
    if (!WRAPPER_KEYS.has(k)) props[k] = v;
  }

  const result = schema.safeParse(props);
  if (result.success) return { ok: true, component, id, unknown: false, issues: [] };

  // Drop issues that are only "wrong static type" because the value is a
  // DataBinding — those resolve at render time and are legal A2UI.
  const realIssues = (result.error?.issues || []).filter(
    (i) => !isBinding(valueAtPath(props, i.path))
  );
  if (realIssues.length === 0) return { ok: true, component, id, unknown: false, issues: [] };

  const issues = realIssues.map(
    (i) => `${i.path.join(".") || "(root)"}: ${i.message}`
  );
  return { ok: false, component, id, unknown: false, issues };
}

/**
 * Validate a full A2UI document (the { a2ui: [...] } shape or a bare message
 * array). Walks every component in every updateComponents message.
 *
 * @returns {{ valid: boolean, checked: number, unknownComponents: string[], failures: Array<{id:string,component:string,issues:string[]}> }}
 */
export function validateA2UIDocument(doc) {
  const messages = Array.isArray(doc) ? doc : Array.isArray(doc?.a2ui) ? doc.a2ui : [];
  const failures = [];
  const unknownComponents = new Set();
  let checked = 0;

  for (const msg of messages) {
    const comps = msg?.updateComponents?.components;
    if (!Array.isArray(comps)) continue;
    for (const node of comps) {
      const r = validateComponent(node);
      if (r.unknown) unknownComponents.add(r.component);
      else {
        checked++;
        if (!r.ok) failures.push({ id: r.id, component: r.component, issues: r.issues });
      }
    }
  }

  return {
    valid: failures.length === 0,
    checked,
    unknownComponents: [...unknownComponents],
    failures,
  };
}
