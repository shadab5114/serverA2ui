# Hard rules

> **Placeholder rules for the GenUI playground.** They stand in for the design-system team's real list
> (open decision D5) so the guideline gate can be wired end to end. Replace them freely.

Hard rules are **checked in code** before a surface reaches the screen: each `## DS-1xx` section here
has a matching deterministic lint in `server/app/verify/lints.py` (a test fails if the two drift apart).
A violation is sent back to the generator with the rule's id and text, exactly like a schema error.
The text below is what the generator and the trace panel quote.

## DS-101 · One primary action per surface

A surface has at most one primary `Button` (a `Button` with `kind: "primary"`, which is the default
when `kind` is omitted), and a primary button never sits inside a repeated list item, where it would
render once per item. Use `kind: "secondary"` for every other action.

## DS-102 · Every input has a visible label

`InputField`, `TextArea`, `CheckboxGroup` and `RadioButtonGroup` always carry a non-empty `label`.
Placeholder text is not a label.

## DS-103 · Badges are short

Badge text (`Badge` children, a tile `cap`, a `Tilelet` badge) is at most 3 words and 24 characters.
Badges highlight; they don't explain.

## DS-104 · Images have alt text

Every `Image` has a non-empty `alt` that describes what it shows.

## DS-105 · Prices come from data

Never write a price into a component as literal text (for example `"$55/mo"`). Seed it in
`updateDataModel` and bind to it with `{ "path": ... }`, so the value can always be traced to its data.
