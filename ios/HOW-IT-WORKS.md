# How the A2UI iOS renderer works

Read this before [README.md](README.md). This is the mental model; the README is
the reference.

---

## 1. The one idea

**The server sends data describing a UI. It never sends a UI.**

A normal app ships screens and the server fills them with data. Here the server
decides the *structure* too — which fields, in what order, with what labels — and
sends it as JSON. The client decides what any of it looks like.

That split is the whole design, and it's why one backend can feed both a React
web app and a SwiftUI iOS app:

```
                    ┌──────────────────────────────────┐
  "sign me up" ───► │ agent: plan → generate → VALIDATE │
                    └───────────────┬──────────────────┘
                                    │  A2UI JSON (platform-neutral)
                                    │  "Button", "InputField", "Column"
                      ┌─────────────┴─────────────┐
                      ▼                           ▼
              React + PDS (web)          SwiftUI + VDS (iOS)
              Button → PDS.Button        Button → VDSButton
```

The payload says `"Button"`. It never says `VDSButton`, never says a colour, a
font, or a corner radius. **Naming and appearance are the renderer's business.**
Push either into the payload and you've forked the backend per platform.

The corollary: nothing on the wire is a promise that iOS can render it. The
generator builds from a catalog, and this renderer maps a subset of it. An
unmapped component draws a visible red placeholder naming what was missing —
deliberately loud, because that's a real and expected state.

---

## 2. Five concepts

Everything in `A2UICore` is one of these.

| Concept | What it is | Swift |
| --- | --- | --- |
| **Surface** | One renderable screen/panel. A chat turn owns one. | `A2UISurface` |
| **Data model** | A JSON blob per surface. The single source of truth for values. | `surface.dataModel` |
| **Component** | A node: `id`, `component` name, and a bag of props. | `ComponentModel` |
| **Binding** | `{"path": "/form/email"}` — a pointer into the data model. | `JSONValue.bindingPath` |
| **Catalog** | Component name → the SwiftUI view that draws it. | `A2UICatalog` |

Two structural facts that trip people up:

**The component list is flat, not a tree.** Hierarchy is by reference — a parent
names its children by id. So components arrive in any order (a list template is
often declared *before* the root that uses it). You index by id first, then walk
from the component whose id is `"root"`.

**Values are either literal or bound.** `"label": "Email"` is literal.
`"value": {"path": "/form/email"}` reads the data model live. A binding can sit
anywhere a value can, including nested inside another prop —
`"title": {"children": {"path": "name"}}` is normal.

---

## 3. The four messages

The entire server-to-client protocol:

| Message | Effect |
| --- | --- |
| `createSurface` | Start a new surface. |
| `updateDataModel` | Write `value` at a JSON Pointer `path` (`"/"` = replace all). |
| `updateComponents` | Upsert components by id. |
| `deleteSurface` | Drop it. |

They're cumulative. A turn is normally `createSurface` → `updateDataModel` →
`updateComponents`, but later messages can patch a live surface — that's how the
agent will update a rendered UI in place rather than redrawing it.

---

## 4. Trace one payload

`test/fixtures/product-list.a2ui.json`, end to end. This is the whole system in
one example.

**Message 2** seeds the data:

```json
{ "products": [ { "name": "Everyday Water Bottle", "price": "$19.99" }, … ] }
```

**Message 3** declares two components — note the template comes first:

```json
{ "id": "product-tile", "component": "Tilelet",
  "title": { "children": { "path": "name" } } }

{ "id": "root", "component": "List",
  "children": { "path": "/products", "componentId": "product-tile" } }
```

What the renderer does:

1. `A2UIMessageProcessor` applies all three messages to an `A2UISurface`.
2. `A2UISurfaceView` finds `"root"` and asks the catalog for `"List"`.
3. `ListView` reads its `children`, finds a **template** (`path` *and*
   `componentId` — that pair is what distinguishes it from a plain binding).
4. It reads `/products`, sees 3 elements, and renders `product-tile` three
   times — each with a `DataContext` anchored at `/products/0`, `/products/1`,
   `/products/2`.
5. Inside each row, `TileletComponentView` resolves
   `title.children = {"path": "name"}`. `"name"` has **no leading slash**, so
   it's relative: anchored at `/products/1` it resolves to `/products/1/name`.

That anchoring is why one declared component renders three different rows. It's
the single cleverest thing in the protocol, and `DataContext.basePath` is the
only state that makes it work.

---

## 5. `children` means four different things

The most common source of renderer bugs, so it gets its own section.

| On the wire | Meaning |
| --- | --- |
| `{"path": "/x", "componentId": "t"}` | Template — repeat `t` per element |
| `["a", "b"]` | References to components `a` and `b` |
| `"signup-form"` | A reference — **if** a component has that id |
| `"Sign up"` | Literal text — because nothing has that id |
| `{"path": "/x"}` | Literal text, read from the data model |

Five wire forms, four meanings — and rows 3 and 4 are the *same JSON type*. The
only thing separating them is a lookup against the surface
(`surface.isComponentId(_:)`). Skip that check and every button on every screen
renders blank.

`A2UIComponentContext.children` collapses all five forms into the four-case
`A2UIChildren` enum, so a component author never touches this.

---

## 6. Data flow and why it's simple here

One rule: **the data model is the only source of truth.** Views never hold form
state.

```
   user types
       │
       ▼
  Binding.set ──► surface.dataModel (@Published)
                         │
                         ▼
              SwiftUI re-renders observers
                         │
                         ▼
              props re-resolve from bindings
```

`context.stringBinding("value")` hands a component a real SwiftUI `Binding`:
reads resolve through the pointer, writes go back into the model. So when a
button fires and the agent asks "what did they type?", the answer is already in
the data model.

This is genuinely simpler than the web renderer, which has to render bound
fields uncontrolled and patch changes back because its components don't re-render
on data changes. Here `@Published` + `@ObservedObject` does it.

If a prop is a literal rather than a binding, `stringBinding` returns `nil` —
there's nowhere to write. Render read-only rather than accepting edits you'll
drop.

---

## 7. Actions

A component's `action` is one of two things:

- **`functionCall`** — the renderer handles it locally, no round trip.
  `setData`, `toggleData`, `openUrl` ship built in. Opening a modal is just
  `setData` on a bound boolean.
- **`event`** — goes to the agent, which replies with more A2UI messages.

`checks` is a **sibling** of `action`, not nested inside it. Each check blocks
the action and surfaces its message while its condition is falsy. `A2UIDispatcher`
evaluates them before doing anything.

Before an `event` leaves, its `context` bindings are resolved — the agent gets
values, not pointers.

> The server has no endpoint to receive events yet (Phase 5). `dispatcher.onEvent`
> fires with the resolved event; wiring it to the server is the next backend
> task, and it should be built once for both clients.

---

## 8. Why three modules

| Module | Depends on | Why separate |
| --- | --- | --- |
| `A2UICore` | Foundation | All protocol logic. Tests run in seconds with no simulator — that's where you'll actually debug. |
| `A2UISwiftUI` | Core + SwiftUI | Views and catalog. Where your design system plugs in. |
| `A2UIClient` | Core | SSE transport. Swappable — the renderer doesn't care where JSON comes from. |

The payoff: you can render a surface from a file with no server, no API key and
no network. That's the fastest debugging loop in the project, and it's what the
Fixtures tab is for.

---

## 9. What changes when

The layering in §8 buys one concrete thing: **a component changing shape is a
one-adapter edit.** Not a convention — a structural guarantee. `A2UICore` knows
four message types, component ids, the `child`/`children` keys and `{path}`
bindings, and nothing else. It would render a catalog of 200 components it has
never heard of exactly the same way. The catalog's only contract is
`(A2UIComponentContext) -> AnyView`, so nothing outside that closure knows a
component's shape, and nothing outside it can break when the shape changes.

| Change | What you touch |
| --- | --- |
| Prop renamed, retyped, new enum case | That component's adapter |
| Component goes leaf → container | Adapter — call `context.childrenView()` |
| Component becomes bindable | Adapter — `string("value")` → `stringBinding("value")` |
| Design system renames the type (`VDSButton` → `VDSCTAButton`) | Adapter |
| New component in the catalog | One `register` call |
| **A2UI protocol version** (new message type, new binding form) | **`A2UICore`** |

That last row is the only thing that should ever send you into `A2UICore`. If a
*component* is making you edit Core, something has been put in the wrong layer.

### The asymmetry to watch

Two different sources of change land in the same adapter, and they fail very
differently:

| Source | How it fails |
| --- | --- |
| The VDS initializer changes | **Compile error.** The compiler marches you to it. |
| The catalog's prop schema changes | **Silently.** `context.string("kind")` returns nil → empty label, default styling, no crash. |

The second is the dangerous one, and it's the unavoidable cost of the payload
being an open bag: prop reads are stringly-typed, so a renamed prop reads as
absent rather than as an error. If `catalog.json` renames `kind` → `variant`,
nothing throws — the button just quietly loses its styling.

This is what the golden fixtures are actually for. `npm test` catches a payload
going *invalid*; the Fixtures tab catches one going *valid but different* — three
known surfaces, rendered offline, where you can see what moved. It's also why
regenerating fixtures is a deliberate command (`npm run fixtures`) and not
something CI does on its own: the diff is the signal, so it shouldn't be
overwritten automatically.

---

## 10. Getting it onto your Mac

Copy **`ios/`** and **`test/fixtures/`**. The fixtures are not optional — they're
the offline render path and what the tests read.

### Step 1 — prove the core works (no Xcode UI, ~30 seconds)

```bash
cd ios/A2UIKit
swift test
```

This is where you'll hit the first compile errors — **this Swift has never been
compiled**, it was written on a Windows machine with no Swift toolchain. Fixing
them here, against pure Foundation code with fast tests, is far easier than
fixing them inside a SwiftUI build. Do this before anything else.

### Step 2 — pick a host

**A. Xcode App project — recommended.** Least friction, real simulator,
full debugger.

1. Xcode → New Project → iOS → App → SwiftUI.
2. File → Add Package Dependencies → **Add Local…** → select `ios/A2UIKit`.
   Add all three libraries.
3. Delete the generated `ContentView.swift`/`App.swift`; add the three files
   from `ios/Demo/`.
4. Drag `test/fixtures/*.a2ui.json` into the target, ticking **Copy Bundle
   Resources**.

**B. `.swiftpm` App Playground** — if you want the single-window Playgrounds
feel. Xcode opens `.swiftpm` packages directly and a local `.package(path:)`
dependency works there. Swift Playgrounds on iPad is oriented toward *remote*
packages, so if you plan to edit on iPad, expect to push `A2UIKit` to a git repo
and depend on it by URL instead.

**C. A classic `.playground`** — only useful for poking at `A2UICore` (decode a
fixture, resolve some pointers). A playground can import a local package's
modules only when both live in the same Xcode **workspace**. Fine for
exploration, wrong for building the app.

If you're unsure, take A. You can always add a playground to the same workspace
later.

### Step 3 — render something offline

Run the app and open the **Fixtures** tab first. No server, no API key. If a
surface looks wrong here, it's a renderer bug and nothing else — which is
exactly the ambiguity you want removed before adding a network.

### Step 4 — go live

```bash
npm run agui     # from the repo root, port 8090
```

The **Chat** tab talks to `http://localhost:8090`, which reaches the host Mac
from the simulator. Plain HTTP needs an Info.plist exception:

```xml
<key>NSAppTransportSecurity</key>
<dict><key>NSAllowsLocalNetworking</key><true/></dict>
```

On a physical device, swap `localhost` for the Mac's LAN address.

### Step 5 — bring in VDS

One registration per component, in `DemoCatalog` and nowhere else:

```swift
var vds = A2UICatalog()
vds.register("Button") { ctx in
    VDSButton(ctx.textContent ?? "", kind: ctx.enumValue("kind") ?? .primary) {
        ctx.performAction()
    }
}
let catalog = A2UICatalog.standard.overlaying(vds)   // later wins
```

Work in this order — it's roughly how often the generator emits them:

`Text` → `Button` → `InputField` → `Toggle` → `Checkbox` → `Tilelet` → the rest.

After each one, reopen the Fixtures tab. Anything you haven't mapped keeps its
built-in stand-in, so the app never stops working mid-migration.

Two things the name map alone won't solve, both absorbed in the adapter:

- **Prop translation.** The payload carries web-catalog prop names and enums
  (`kind`, `size`, `surface`). If `VDSButton.init` names them differently, the
  adapter translates. String-backed VDS enums come across with
  `ctx.enumValue("kind")`.
- **Coverage gaps.** The generator can emit components VDS has no equivalent
  for. The placeholder shows you which — decide then whether to build one, alias
  it to something close, or leave it.

---

## 11. Where to look when something's wrong

| Symptom | Look at |
| --- | --- |
| Blank buttons / missing labels | The `children` text-vs-reference check (§5) |
| Red placeholder | Component name not registered in the catalog |
| Empty surface | No component with id `"root"` |
| Bound text empty | Pointer is wrong — relative vs absolute (§4) |
| Every chat bubble shows the newest UI | Missing per-turn `rewritingSurfaceId` |
| Typing doesn't stick | Prop is a literal, not a binding — `stringBinding` returned nil |
| `3.0` where `3` belongs | Read via `displayString`, not raw number formatting |

Each of these is pinned by a test in
`Tests/A2UICoreTests/GoldenFixtureTests.swift`. If you change protocol handling,
run `swift test` — it'll tell you which invariant you broke.
