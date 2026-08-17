---
name: design-with-vds
description: MANDATORY — load this skill BEFORE generating, building, or editing any screen, layout, component, or UI element with the Figma agent. Trigger on any request to create, design, build, mock up, or update a screen, page, modal, form, table, nav, card, or any composite UI pattern. Forces exhaustive design-system-library discovery before generation, defines a matching/decomposition decision tree so rising component complexity is handled by composing existing components instead of falling back to custom-drawn shapes, and requires a pre-handoff audit that catches any non-library layers before the agent reports done.
---

# design-with-vds

## Why this skill exists

Left to its own defaults, the agent does two things that quietly break design-system fidelity:

1. It searches the library shallowly — checks a couple of obvious names, doesn't find an exact hit, and starts drawing.
2. As a requested pattern gets more complex (a data table, a multi-step form, a settings panel), the number of *plausible* existing-component combinations grows, but the agent's patience for trying them doesn't — so it reverts to raw rectangles, manual text layers, and freehand icons for exactly the parts of the screen that most need to stay on-system.

This skill's job is to remove the judgment call. Discovery is mandatory and exhaustive, custom drawing is disallowed by default, and rising complexity is handled by **decomposing into more known components**, not by **abandoning known components**.

## Step 1 — Discovery is mandatory before any generation

Before placing a single frame, shape, or text layer:

1. Identify the target library the user pointed to (or the most recently/frequently used library if none was specified — confirm this assumption with the user in one line before continuing).
2. Search the library for every distinct UI element the request implies — not just the obvious top-level ones. A "checkout form" implies: input fields, labels, error/helper text, a select or dropdown, a checkbox, a primary button, possibly a stepper or progress indicator.
3. For each implied element, record: the closest exact-name match, the closest semantic match if no name matches, and the confidence (exact / partial / none).
4. Do not begin composing the screen until this inventory is complete. Post it as a short checklist so the matching decision in Step 2 is auditable, not silent.

Never generate from a single pass of "does an obviously-named component exist?" — that's the shallow search that causes the misses you're seeing.

## Step 2 — Matching decision tree

Apply this per element, in order. Stop at the first match.

| Situation | Action |
|---|---|
| **Exact match exists** (name or unambiguous semantic equivalent) | Use the component instance directly. Set props/variants — never detach it. |
| **Partial match exists** (right component family, wrong variant/state/size) | Use the base component instance, apply the closest variant, override only exposed properties (text, icon slot, state). Still an instance, never detached. |
| **No single component matches, but the pattern decomposes** | Compose from 2+ existing components via nesting/auto-layout (see Step 3). This is the default for anything "complex" — decomposition, not drawing. |
| **Truly nothing in the library covers this, even decomposed** | STOP. Do not draw a custom replacement silently. Go to Step 4 (escalation). |

"No exact match" almost never means "draw it." It almost always means "go one level down in Step 3."

## Step 3 — Handling rising complexity (the core fix)

This is where the fallback-to-custom failure mode happens, so treat it as a hierarchy problem, not a generation problem. Before treating any pattern as "too complex for the library," break it into its known sub-parts:

| Composite pattern | Decompose into (use existing instances for each) |
|---|---|
| Data table | Table/container component + header row + row component + cell component + text style + badge/tag for status cells + icon buttons for row actions |
| Multi-step form / wizard | Stepper/progress component + section/card container + input field components + button component (primary/secondary) + divider |
| Settings panel | List/row component + toggle or checkbox component + label + helper text style + section header text style |
| Modal / dialog | Modal container/shell component + header slot + body slot (built from other known components) + footer button group |
| Empty state | Illustration/icon slot (existing asset, not custom art) + heading text style + body text style + button component |
| Notification / toast | Toast/banner container component + icon component + text style + close/dismiss icon button |
| Nav / sidebar | Nav container + nav item component + icon component + active-state variant |
| Card grid | Card component + image/media slot + text styles + tag/badge component, repeated in an auto-layout grid |

If a pattern isn't in this table, apply the same logic manually: name every sub-element out loud, search each one individually per Step 1, and only escalate the parts that individually have no match — not the whole composite.

A component being "complex" is a reason to decompose harder, never a reason to stop searching.

## Step 4 — Escalation instead of silent fallback

If, after decomposition, one or more sub-elements genuinely have no library equivalent:

1. **Stop generating that element.** Do not substitute a custom shape without saying so.
2. Tell the user exactly what's missing — name the element and where it sits in the layout.
3. Offer two explicit options, and wait for a choice before proceeding:
   - **(a) Placeholder:** build it from the closest existing primitives, and visually/label it as a temporary non-DS placeholder (e.g. name the layer `TEMP – not in DS: [element]`) so it's trivially findable later.
   - **(b) Pause:** stop that section of the build and flag it as a design-system gap for the team to formalize, rather than inventing a one-off that will drift.
4. Never invent a new component silently and never name a custom layer as if it were a real library component — that's what makes gaps invisible later.

## Step 5 — Hard rules (apply throughout, not just at decision points)

- Never draw a rectangle + manual text layer to stand in for a button, input, chip, or any element with a library equivalent, even "just to block out layout."
- Never detach a component instance to tweak it. If the needed change isn't an exposed property, that's a Step 4 gap — escalate it, don't detach-and-hack.
- Never hardcode a color, spacing value, radius, or font size. Every value must bind to a token/variable or style from the library. A hardcoded hex is the same category of drift as a custom shape.
- Never treat "I couldn't find it quickly" as equivalent to "it doesn't exist." Re-run discovery with synonyms (e.g. "dropdown" / "select" / "combobox") before concluding no match.
- Never let complexity be the trigger for abandoning the library. Complexity is the trigger for decomposing further (Step 3).

## Step 6 — Pre-handoff audit

Before reporting the build as done, scan the canvas and check:

- [ ] Every interactive element (button, input, toggle, tag, nav item, etc.) is a component instance, not a raw shape/text group.
- [ ] No instance was detached from its main component.
- [ ] All colors, type, spacing, and radii resolve to variables/styles, not literal values.
- [ ] Any placeholder or escalated element from Step 4 is clearly labeled and was explicitly approved by the user.
- [ ] Nothing was silently substituted.

If any box fails, fix it before calling the task complete — don't report success with known gaps unmentioned.

## Step 7 — Reporting contract

When the build is finished, always report:

1. **Components used** — name + variant, grouped by section of the screen.
2. **Placeholders/escalations** — anything from Step 4, with the choice the user made.
3. **Anything you're not fully confident is on-system** — flag it even if it passed the audit, rather than staying silent on uncertainty.
