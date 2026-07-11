/**
 * Sanity-check (and lightly repair) the component graph the LLM produced.
 *
 * The renderer builds the UI by walking `child`/`children` references starting
 * at the component with id "root". If a component is never referenced from root
 * it is an ORPHAN and renders nothing; if root's `children` is a bare `{ path }`
 * binding with no seeded data, the whole surface comes up blank. This module
 * catches those cases and, where possible, repairs them so the UI still renders.
 *
 * Only `child` and `children` create child components in this catalog — every
 * other property is a plain value — so reachability is defined purely by them.
 *
 * @param {{ a2ui?: any[] }} doc  The generated A2UI document ({ a2ui: [...] }).
 * @returns {{ repaired: boolean, warnings: string[], errors: string[] }}
 */
export function validateAndRepairGraph(doc) {
  const warnings = [];
  const errors = [];
  let repaired = false;

  const messages = Array.isArray(doc?.a2ui) ? doc.a2ui : [];
  const components = [];
  for (const m of messages) {
    const list = m?.updateComponents?.components;
    if (Array.isArray(list)) components.push(...list);
  }

  if (components.length === 0) {
    errors.push("No components found (no updateComponents.components).");
    return { repaired, warnings, errors };
  }

  const byId = new Map();
  for (const c of components) {
    if (!c || typeof c.id !== "string") {
      errors.push(`A component is missing a string "id": ${JSON.stringify(c)}.`);
      continue;
    }
    if (byId.has(c.id)) errors.push(`Duplicate component id "${c.id}".`);
    byId.set(c.id, c);
  }

  // Which ids does a component reference as children?
  //  - hard: shapes that are unambiguously references (must exist).
  //  - soft: a single string `children` that is a reference only if it names a
  //    known component (otherwise it is text content, e.g. a Button label).
  const refsOf = (comp) => {
    const hard = [];
    const soft = [];
    if (typeof comp.child === "string") hard.push(comp.child);
    const ch = comp.children;
    if (Array.isArray(ch)) {
      for (const v of ch) {
        if (typeof v === "string") hard.push(v);
        else if (v && typeof v.id === "string") hard.push(v.id);
      }
    } else if (ch && typeof ch === "object" && typeof ch.componentId === "string") {
      hard.push(ch.componentId); // list template
    } else if (typeof ch === "string") {
      soft.push(ch);
    }
    return { hard, soft };
  };

  const isTemplateChildren = (comp) =>
    comp.children && typeof comp.children === "object" &&
    !Array.isArray(comp.children) && typeof comp.children.componentId === "string";

  // Referenced set + dangling detection.
  const referenced = new Set();
  for (const c of components) {
    const { hard, soft } = refsOf(c);
    for (const id of hard) {
      if (byId.has(id)) referenced.add(id);
      else errors.push(`Component "${c.id}" references missing child id "${id}".`);
    }
    for (const id of soft) if (byId.has(id)) referenced.add(id);
  }

  const roots = components.filter((c) => c.id === "root");
  if (roots.length === 0) {
    errors.push('No component has id "root" — the tree has no entry point.');
    return { repaired, warnings, errors };
  }
  if (roots.length > 1) errors.push('More than one component has id "root".');
  const root = roots[0];

  // Orphans: non-root components nothing references.
  const orphans = components
    .filter((c) => c.id !== "root" && typeof c.id === "string" && !referenced.has(c.id))
    .map((c) => c.id);

  if (orphans.length > 0) {
    if (isTemplateChildren(root)) {
      // Root drives a dynamic list template; we can't safely fold static
      // orphans into it. Report rather than guess.
      warnings.push(
        `Orphan components not attached (root uses a list template): ${orphans.join(", ")}.`
      );
    } else {
      // Rebuild root.children as an explicit array: existing valid refs + orphans.
      const existing = [];
      if (typeof root.child === "string" && byId.has(root.child)) {
        existing.push(root.child);
        delete root.child;
      }
      const rch = root.children;
      if (Array.isArray(rch)) {
        for (const v of rch) if (typeof v === "string" && byId.has(v)) existing.push(v);
      } else if (typeof rch === "string" && byId.has(rch)) {
        existing.push(rch);
      }
      // If root.children was a useless binding (e.g. { path: "form" }) it is
      // simply dropped here in favor of the explicit list.
      root.children = [...new Set([...existing, ...orphans])];
      repaired = true;
      warnings.push(
        `Attached ${orphans.length} orphan component(s) to root: ${orphans.join(", ")}.`
      );
    }
  }

  return { repaired, warnings, errors };
}
