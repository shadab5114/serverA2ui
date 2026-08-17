// Golden-fixture tests for the catalog validator (A2UI-BACKEND-ARCHITECTURE.md
// Phase 2 "done when": a hand-written A2UI payload validates, and a broken one
// fails, via the design system's shipped schemas).
//
// Run: npm test

import { test } from "node:test";
import assert from "node:assert/strict";
import {
  validateA2UIDocument,
  validateComponent,
  KNOWN_COMPONENTS,
} from "../src/catalogSchemas.js";

const surface = (components) => ({
  a2ui: [
    { version: "v0.9", createSurface: { surfaceId: "main", catalogId: "x" } },
    { version: "v0.9", updateComponents: { surfaceId: "main", components } },
  ],
});

test("the design system exposes schemas for its components", () => {
  assert.ok(KNOWN_COMPONENTS.includes("Button"));
  assert.ok(KNOWN_COMPONENTS.includes("InputField"));
  assert.ok(KNOWN_COMPONENTS.length >= 30);
});

test("a valid hand-written payload passes", () => {
  const doc = surface([
    { id: "root", component: "Button", children: "Sign in", kind: "primary", size: "large", disabled: false },
    { id: "email", component: "InputField", label: "Email", value: { path: "/form/email" } },
  ]);
  const r = validateA2UIDocument(doc);
  assert.equal(r.valid, true, JSON.stringify(r.failures));
  assert.equal(r.checked, 2);
});

test("a bad enum value fails", () => {
  const r = validateComponent({ id: "b", component: "Button", children: "x", kind: "tertiary" });
  assert.equal(r.ok, false);
  assert.ok(r.issues.some((i) => i.includes("kind")), JSON.stringify(r.issues));
});

test("a wrong-typed prop fails", () => {
  const r = validateComponent({ id: "b", component: "Button", children: "x", disabled: "yes" });
  assert.equal(r.ok, false);
  assert.ok(r.issues.some((i) => i.includes("disabled")), JSON.stringify(r.issues));
});

test("a broken payload is reported as invalid with failures", () => {
  const doc = surface([
    { id: "root", component: "Button", children: "ok", kind: "primary" },
    { id: "bad", component: "Button", children: "x", size: "gigantic" },
  ]);
  const r = validateA2UIDocument(doc);
  assert.equal(r.valid, false);
  assert.equal(r.failures.length, 1);
  assert.equal(r.failures[0].id, "bad");
});

test("unknown / non-pds components are reported, not failed", () => {
  const doc = surface([
    { id: "root", component: "Column", children: ["a"] }, // borrowed layout, no pds schema
    { id: "a", component: "Button", children: "hi" },
  ]);
  const r = validateA2UIDocument(doc);
  assert.equal(r.valid, true);
  assert.ok(r.unknownComponents.includes("Column"));
  assert.equal(r.checked, 1); // only the Button was schema-checked
});

test("extra props the DS doesn't describe (e.g. action) are tolerated", () => {
  // The generator prompt encourages `action` on interactive components even
  // though the props schema doesn't list it; leniency avoids false rejections.
  const r = validateComponent({
    id: "b",
    component: "Button",
    children: "Submit",
    action: { event: { name: "submit" } },
  });
  assert.equal(r.ok, true, JSON.stringify(r.issues));
});
