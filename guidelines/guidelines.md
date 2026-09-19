# Design guidelines and patterns

> **Placeholder guidance for the GenUI playground**, written to exercise retrieval, the design brief and
> the guideline judge until the real guidance is served by RAG (open decision D2). Replace freely.

Soft guidelines (`DS-2xx`) are judged by a model against the generated surface; patterns (`PAT-3xx`)
are approved compositions the design brief can pick. Hard rules live in `hard-rules.md`.

## DS-201 · Lead with one clear title

Start a surface with a single title (`Text` with `kind: "title"`, or a `TitleLockup`), then an optional
one-line summary. Don't stack several competing headings.

## DS-202 · Stack with Column, align with Row

Use `Column` for vertical stacks and `Row` for 2–4 items side by side. Nest containers rather than
relying on components to space themselves; design-system components add no outer spacing.

## DS-203 · Consistent option tiles

When showing options (plans, products, add-ons) as tiles, every tile shows the same fields in the same
order: badge (optional), name, price, the key facts, then its action. Use `ComposableTileContainer` or
`Tilelet`. Keep one action per tile, labelled with a verb.

## DS-204 · Badges are for highlights

Use at most one badge per tile, for a real highlight ("Best value", "Recommended"). Don't badge every
option; a badge on everything highlights nothing.

## DS-205 · Action labels are verbs in sentence case

Buttons say what happens: "Choose plan", "Continue", "Save changes". Not "Click here", "OK" or
ALL CAPS.

## DS-206 · Forms are short and grouped

Ask only for what's needed. Group related fields in a `Column`, put the primary submit button last, and
validate with `checks` on the submit action rather than with error text written in advance.

## DS-207 · Status messages use Notification

System feedback (success, warning, error, info) uses `Notification` with the matching `kind`, not
colored `Text`.

## DS-208 · Recommend with reasons, not just rankings

When helping someone choose, say why an option fits their stated need in one short line next to it,
and keep the other suitable options visible so the choice stays theirs.

## DS-209 · Show only real data

Names, prices and features come from the data you were given. If the request needs data you don't
have (for example network coverage), leave it out and say so, rather than inventing values.

## PAT-301 · Recommendation (compare options for a need)

For "which X fits me?" requests.
Composition: `Column` root → title `Text` → one-line summary of the user's need → `Row` of 2–3 option
tiles (`ComposableTileContainer`), the best fit first with a `cap` badge "Recommended" → in each tile:
name, price, the 2–3 facts that matter for the stated need, a one-line "why it fits", one secondary
"Choose" button. Relies on: DS-203, DS-204, DS-208, DS-209.

## PAT-302 · Short form

For sign-up, contact and settings requests.
Composition: `Column` root → title → labelled fields (`InputField`, `Checkbox`) bound two-way to
`/form/...` → one primary submit `Button` last, with `checks` for required fields and an `event` action.
Relies on: DS-102, DS-206, DS-101.

## PAT-303 · Summary with next step

For confirming a choice.
Composition: `Column` root → title → `Notification` (kind success) summarizing what was chosen →
key facts as `Text` → one primary `Button` for the next step. Relies on: DS-207, DS-101.
