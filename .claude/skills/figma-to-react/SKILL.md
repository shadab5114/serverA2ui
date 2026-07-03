---
name: figma-to-react
description: Convert a Figma node JSON export (plus an optional screenshot of the node) into a React page/component built with @shadab5114/pds-core (PDS) design-system components. Use when the user provides Figma JSON and/or a design screenshot and wants React code that mimics the design.
---

# Figma → React (PDS components)

Build a React component that visually mimics a Figma design, using `@shadab5114/pds-core`
components wherever one applies and plain JSX only for what the design system does not cover.

**Inputs:** a Figma node JSON file (required) and a screenshot of the node (strongly recommended).
**Prerequisite:** run inside a repo where `@shadab5114/pds-core` is installed.

## Hard rules

- NEVER Read the raw Figma JSON file — it is huge. Always distill it first (step 1).
- Only use props that exist in the catalog (step 3). Never invent props.
- The screenshot is the visual ground truth (hierarchy, emphasis, what "looks like" a PDS
  component). The distilled JSON is the ground truth for exact text, spacing, and variant values.

## Workflow

### 1. Distill the Figma JSON

```
node <skill-dir>/scripts/distill-figma.mjs <path-to-figma.json>
```

This prints a compact indented tree: node types, names, component-instance variant props,
text content, auto-layout (direction/gap/padding), colors, and sizes. Work from this only.

### 2. Look at the screenshot

Read the screenshot image if provided. Note overall layout, groupings, emphasis, and any
element that resembles a PDS pattern even where Figma used raw frames/text.

### 3. Get the component inventory

```
node <skill-dir>/scripts/list-components.mjs            # all components, one-line prop summary
node <skill-dir>/scripts/list-components.mjs Tilelet    # full JSON schema for one component
```

This reads `@shadab5114/pds-core/catalog.json` resolved from the working repo, so it always matches
the installed version. Fetch the full schema for every component you decide to use before
writing code. (If the script fails to resolve the package, stop and tell the user the repo is
missing `@shadab5114/pds-core`.)

### 4. Map Figma nodes → PDS components

- Strip vendor prefixes from instance names (`[VDS] `, `PDS/`, etc.), collapse spaces, and
  match PascalCase against catalog component names.
  Known aliases: `Tile Container` → `TileContainer`, `Tile`/`Tilelet` → `Tilelet`,
  `Title Lockup` → `TitleLockup`, `Text Link` → `TextLink`, `CTA`/`Button` → `Button`.
- Map Figma variant properties to catalog enums by case-normalizing values
  (`"Primary"` → `"primary"`). Drop Figma-internal properties that have no catalog
  counterpart (`Padding Guide`, `Keyboard Focus`, `aspectRatio`, numbered `#id` suffixes).
- **Prefer a PDS component whenever one fits**, even if Figma modeled it as raw text/frames:
  a heading + subtitle pair is a `TitleLockup`; a bordered/shadowed card is a
  `TileContainer`/`Tilelet`; a pill label is a `Badge`. Use the screenshot to judge this.
- Nodes with no PDS equivalent: plain JSX with minimal inline styles derived from the
  distilled layout — `layoutMode VERTICAL/HORIZONTAL` → flex column/row, `gap`, `pad`,
  `bg`/text colors, `radius`. Do not pixel-chase absolute positions; use flex.

### 5. Generate the code

- One `.tsx` file, named after the Figma frame, following the working repo's existing
  component conventions (check a sibling component for style).
- `import { Button, Tilelet, ... } from "@shadab5114/pds-core";`
- Text content verbatim from the distilled `characters` lines. Real data that varies per
  user (names, phone numbers) becomes props of the generated component with the Figma
  values as defaults.
- Assume the app shell already imports the PDS stylesheet; do not re-add global CSS.

### 6. Verify

- Typecheck/build with the repo's own script (`tsc --noEmit` or `npm run build`).
- Re-compare against the screenshot; state any deliberate deviations (fonts, icons,
  imagery you could not reproduce) in your summary.
