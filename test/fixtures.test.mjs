/**
 * Contract tests for the golden fixtures in test/fixtures/.
 *
 * The fixtures are the shared conformance input for every renderer (the React
 * client and ios/A2UIKit). They were captured from a real generation, so they
 * must stay catalog-valid: if a catalog or prompt change makes them invalid,
 * they are no longer describing UI the server can actually produce, and the
 * renderers are being tested against fiction. Regenerate with `npm run
 * fixtures` when that happens.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { validateAndRepairGraph } from "../src/validateGraph.js";
import { validateA2UIDocument } from "../src/catalogSchemas.js";

const DIR = join(dirname(fileURLToPath(import.meta.url)), "fixtures");
const files = readdirSync(DIR).filter((f) => f.endsWith(".a2ui.json"));

test("fixtures exist", () => {
  assert.ok(files.length > 0, "no fixtures found — run `npm run fixtures`");
});

for (const file of files) {
  const fixture = JSON.parse(readFileSync(join(DIR, file), "utf8"));

  test(`${file} — is a well-formed A2UI document`, () => {
    assert.ok(Array.isArray(fixture.a2ui), "missing a2ui message list");
    for (const message of fixture.a2ui) {
      assert.equal(message.version, "v0.9");
      const keys = Object.keys(message).filter((k) => k !== "version");
      assert.equal(keys.length, 1, `expected exactly one message key, got ${keys}`);
    }
  });

  test(`${file} — component graph is sound and needs no repair`, () => {
    // Deep-copy: validateAndRepairGraph mutates, and a fixture that only passes
    // AFTER repair is not a fixture a renderer can trust.
    const doc = structuredClone({ a2ui: fixture.a2ui });
    const result = validateAndRepairGraph(doc);
    assert.deepEqual(result.errors, [], "graph errors");
    assert.equal(result.repaired, false, "fixture should not need repair");
  });

  test(`${file} — every component validates against the catalog`, () => {
    const result = validateA2UIDocument({ a2ui: fixture.a2ui });
    assert.deepEqual(
      result.failures.map((f) => `${f.id}(${f.component}): ${f.issues.join(", ")}`),
      []
    );
  });
}
