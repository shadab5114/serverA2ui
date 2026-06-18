# A2UI Client — paste & preview

A React + Vite app to test **A2UI v0.9** rendering. Paste A2UI JSON on the left
(e.g. the output of the `/generate` server in this repo, or any A2UI JSON),
click **Render**, and the UI renders on the right using the **@pds/core** design
system via the **@a2ui/react** renderer.

## How it works

```
paste JSON ─► extract A2UI messages ─► MessageProcessor([pdsCatalog]) ─► <A2uiSurface/>
                                              │
                                   @pds/core components wrapped as an
                                   A2UI catalog (src/pdsCatalog.tsx)
```

- `src/pdsCatalog.tsx` builds the catalog: each `@pds/core` component is wrapped
  with `createBinderlessComponentImplementation`, and its zod schema from
  `@pds/core/schemas` is attached as the component contract.
- It resolves A2UI values itself: data bindings `{ "path": "/x" }`, single child
  refs (`child`), static child lists, and `{ "path", "componentId" }` list
  templates (repeating a component over a data-model array).
- `@pds/core` and `@a2ui/react` base styles are injected in `src/main.tsx`.

## Prerequisites: link the local packages

Two local packages are linked with npm:
- **`@pds/core`** — the design-system components + zod schemas.
- **`pdesign-tokens`** — the CSS custom properties (`--pdesign-*`) that
  `@pds/core`'s component CSS references. **Required**, or components render
  unstyled.

```bash
# 1. Register both built packages globally (run once each)
cd /d/DesignSystem/pds/dist/@pds/core && npm link
cd /d/DesignSystem/pds-tokens && npm link

# 2. Link BOTH into this client in a single command
cd /d/ServerSetupA2UI/client
npm link @pds/core pdesign-tokens
```

> ⚠️ **Link both together.** Running `npm link <one>` (or `npm install`)
> afterwards **prunes** any linked package not listed in `package.json` — so
> linking them one at a time removes the first. Always re-link both in one
> command after an `npm install`.

> If you rebuild the design system / tokens, the symlinks pick up the new `dist`
> automatically (restart Vite to clear its dep cache).

## Install & run

```bash
cd client
npm install
npm link @pds/core pdesign-tokens   # re-link both (npm install prunes links)
npm run dev                          # http://localhost:5176
```

Build: `npm run build` · Preview build: `npm run preview`

## Using it

1. In Postman, hit your server's `POST /generate` and copy the JSON response.
2. Paste it into the left pane (the whole `{ "meta": ..., "a2ui": [...] }`
   object works — `meta` is ignored).
3. Click **Render**. A sample is preloaded; **Load sample** restores it.

Accepted input shapes:
- `{ "a2ui": [ ...messages ] }` (this repo's server output)
- a bare array of A2UI messages
- a single A2UI message object
- an A2A JSON-RPC envelope (`result.status.message.parts[].data`)

Every surface's `catalogId` is normalized to the registered `@pds/core`
catalog, so JSON generated against `https://pdesign.dev/catalog/v1/catalog.json`
renders without edits.

## Supported components

Whatever `@pds/core` exports and the catalog defines — currently: Button,
TextLink, TextLinkCaret, ButtonGroup, Text, Caret, DirectionalIcon, Tooltip,
Badge, BadgeIndicator, Image, TileContainer, TitleLockup, TitleLockupTitle,
TitleLockupSubtitle, TitleLockupEyebrow, ScreenReaderText, Tilelet.

## Notes / gotchas

- **React is deduped** in `vite.config.ts` so the linked `@pds/core` shares the
  app's single React copy (avoids "invalid hook call").
- The renderer is **binderless on purpose**: `@a2ui`'s generic binder inspects
  zod-v3 schema internals to find A2UI primitives, but `@pds/core` schemas are
  zod v4 and describe component props (`children: z.any()`), so we resolve
  bindings/children ourselves from the component context.
