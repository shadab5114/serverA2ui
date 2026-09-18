/**
 * Regenerate the golden A2UI fixtures in test/fixtures/.
 *
 *   npm run fixtures
 *
 * Lives outside test/ on purpose: `npm test` runs `node --test test/`, which
 * treats every .mjs under that directory as a test file — leaving this there
 * would fire three LLM calls on every test run.
 *
 * Fixtures are captured through the REAL validator-gated pipeline
 * (agent/uiGenerator.js) — the same path the chat flow uses — so they are
 * identical in shape to what a client receives over the wire. They are the
 * shared conformance input for every A2UI renderer (React today, iOS/SwiftUI
 * next): both must render the same bytes the same way.
 *
 * Regenerating calls the LLM and will produce DIFFERENT layouts. Do it only
 * deliberately (e.g. after a catalog or prompt change), and re-check the
 * renderers against the new output — that diff is the point.
 */
import "dotenv/config";
import { writeFile, mkdir } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { generateValidatedA2UI } from "../agent/uiGenerator.js";

const OUT = join(dirname(fileURLToPath(import.meta.url)), "..", "test", "fixtures");

/** Each case targets a distinct renderer capability — keep them that way. */
const CASES = [
  {
    file: "signup-form.a2ui.json",
    name: "signup-form",
    description:
      "Static form: layout container, labelled input fields and a submit button. Exercises children-as-text (button label) vs children-as-component-ids, and form controls.",
    prompt:
      "Create a sign-up form with a title, a full name field, an email field, a password field, and a submit button.",
  },
  {
    file: "product-list.a2ui.json",
    name: "product-list",
    description:
      "Data-bound list: updateDataModel seeds an array and root uses a { path, componentId } child template. Exercises JSON-Pointer bindings and relative paths inside a repeated template.",
    prompt:
      "Show a list of 3 products, each with a name, a price and a short description, rendered as tiles from a data model.",
  },
  {
    file: "settings-panel.a2ui.json",
    name: "settings-panel",
    description:
      "Interactive surface: toggles/checkboxes bound two-way to the data model plus a button carrying an action. Exercises two-way binding and action dispatch.",
    prompt:
      "Build a notification settings panel with a heading, a toggle for email alerts, a toggle for push alerts, a checkbox to agree to terms, and a Save button that submits the settings.",
  },
];

await mkdir(OUT, { recursive: true });

for (const c of CASES) {
  process.stdout.write(`generating ${c.name}… `);
  const result = await generateValidatedA2UI(c.prompt);
  if (!result.ok) {
    console.log(`FAILED: ${result.errors.join(" | ")}`);
    process.exitCode = 1;
    continue;
  }

  const messages = result.a2ui.a2ui;
  const fixture = {
    $comment:
      "GOLDEN FIXTURE — captured from the real validator-gated generator. " +
      "Shared conformance input for every A2UI renderer. Regenerate with " +
      "`npm run fixtures`, only deliberately.",
    name: c.name,
    description: c.description,
    prompt: c.prompt,
    capturedAt: new Date().toISOString(),
    generator: { provider: result.meta.provider, model: result.meta.model },
    a2ui: messages,
  };
  await writeFile(join(OUT, c.file), JSON.stringify(fixture, null, 2) + "\n", "utf8");

  const kinds = messages.map((m) => Object.keys(m).find((k) => k !== "version"));
  const comps = messages.flatMap((m) => m.updateComponents?.components ?? []);
  console.log(
    `ok — ${messages.length} msgs [${kinds.join(" → ")}], ${comps.length} components, ${result.meta.attempts} attempt(s)`
  );
  console.log(`   components: ${[...new Set(comps.map((x) => x.component))].join(", ")}`);
}
