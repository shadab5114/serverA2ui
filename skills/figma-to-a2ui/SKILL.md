---
name: figma-to-a2ui
description: Convert a Figma node JSON export (plus an optional screenshot of the node) into an A2UI v0.9 JSON payload using the @shadab5114/pds-core component catalog. Use when the user provides Figma JSON and/or a design screenshot and wants A2UI JSON (surface/components/data-model messages) that mimics the design.
---

# Figma → A2UI v0.9 (PDS catalog)

Produce an A2UI v0.9 message payload that renders the given Figma design using components
from the `@shadab5114/pds-core` catalog.

**Inputs:** a Figma node JSON file (required) and a screenshot of the node (strongly recommended).
**Prerequisite:** run inside a repo where `@shadab5114/pds-core` is installed.

## Hard rules

- NEVER Read the raw Figma JSON file — it is huge. Always distill it first (step 1).
- Only use component types and props that exist in the catalog (step 3). Never invent either.
- Read [references/a2ui-format.md](references/a2ui-format.md) before writing any A2UI JSON;
  the envelope format is strict and easy to get wrong.
- The screenshot is the visual ground truth; the distilled JSON is the ground truth for
  exact text, spacing, and variant values.

## Workflow

### 1. Distill the Figma JSON

```
node <skill-dir>/scripts/distill-figma.mjs <path-to-figma.json>
```

Prints a compact indented tree: node types, names, instance variant props, text content,
auto-layout, colors, sizes. Work from this only.

### 2. Look at the screenshot

Read the screenshot image if provided; note layout, groupings, and emphasis.

### 3. Get the component inventory

```
node <skill-dir>/scripts/list-components.mjs            # all components + catalogId
node <skill-dir>/scripts/list-components.mjs Tilelet    # full JSON schema for one component
```

Reads `@shadab5114/pds-core/catalog.json` resolved from the working repo. Note the printed
`catalogId` — it goes into `createSurface`. Fetch the full schema for every component you
use: it tells you which props are plain values, which are `DynamicString`, and which are
object-shaped (e.g. a title prop of the form `{ "children": <DynamicString> }`).

### 4. Map Figma nodes → catalog components

- Strip vendor prefixes from instance names (`[VDS] `, `PDS/`, etc.), collapse spaces, and
  match PascalCase against catalog names. Known aliases: `Tile Container` → `TileContainer`,
  `Tile`/`Tilelet` → `Tilelet`, `Title Lockup` → `TitleLockup`, `Text Link` → `TextLink`,
  `CTA`/`Button` → `Button`.
- Map Figma variant values onto catalog enums by case-normalizing (`"Primary"` → `"primary"`).
  Drop Figma-internal properties (`Padding Guide`, `Keyboard Focus`, `aspectRatio`, `#id`
  suffixes) that have no catalog counterpart.
- Prefer a catalog component whenever one fits, even if Figma modeled it as raw text/frames
  (heading + subtitle → `TitleLockup`; a card → `TileContainer`/`Tilelet`).
- There are no arbitrary styled divs in A2UI: structure that has no catalog match must be
  expressed with the closest container component in the catalog, or noted as a limitation
  in your summary.

### 5. Compose the payload

Follow [references/a2ui-format.md](references/a2ui-format.md) exactly. In short:
`{"a2ui": [...]}` with `createSurface` → `updateDataModel` → `updateComponents`; a flat
component list with exactly one `"id": "root"`.

Data-model policy: static copy stays inline in component props; user/entity-specific values
(names, phone numbers, device names) and repeated collections go into the data model and are
referenced with `{ "path": "/..." }` bindings — collections use the children list-template
form. Take the concrete values from the distilled Figma text verbatim.

Write the payload to a `.json` file named after the Figma frame (or where the user asks).

### 6. Validate

```
node <skill-dir>/scripts/validate-a2ui.mjs <payload.json>
```

Fix every error it reports (unknown component types, missing root, dangling child
references, malformed messages) and re-run until clean. In your summary, state any parts of
the design the catalog could not express.
