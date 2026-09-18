# A2UIKit — iOS/SwiftUI renderer for A2UI v0.9

> New here? Read **[HOW-IT-WORKS.md](HOW-IT-WORKS.md)** first — the mental model,
> a worked example, and how to get this running on a Mac. This file is the
> reference.

Renders the same A2UI payloads the React client renders, from the same server.
The wire format is platform-neutral: component names on it are catalog names
(`Button`, `Badge`, `InputField`), and this package decides what they look like
on iOS.

Mirrors the web split so the two renderers stay comparable:

| Web | Here |
| --- | --- |
| `@a2ui/web_core` | `A2UICore` — Foundation only, no SwiftUI |
| `@a2ui/react` | `A2UISwiftUI` — views, catalog, built-in components |
| `fetch` + SSE parsing in `Chat.tsx` | `A2UIClient` — `AGUIClient` |

## Status

`A2UICore` and its tests are the load-bearing part and are covered by the golden
fixtures in `test/fixtures/`. **None of this Swift has been compiled** — it was
written on a Windows machine with no Swift toolchain. Expect to fix compile
errors on first build; the logic and the protocol handling are the parts worth
trusting, not the syntax.

Start with `swift test` (macOS, no simulator needed) — it exercises the pointer
implementation, the message decoding and every binding shape in the fixtures.
That is the fastest way to shake out the first round of errors.

## Setup

```bash
cd ios/A2UIKit
swift test          # A2UICore conformance tests against test/fixtures/
```

For the demo app (Xcode, macOS only):

1. New Xcode project → iOS App → SwiftUI.
2. File → Add Package Dependencies → Add Local… → select `ios/A2UIKit`.
   Add all three libraries (`A2UICore`, `A2UISwiftUI`, `A2UIClient`).
3. Delete the generated `ContentView.swift` / `App.swift` and add the three
   files from `ios/Demo/`.
4. Drag `test/fixtures/*.a2ui.json` into the target's **Copy Bundle Resources**
   so the Fixtures tab can load them.
5. For the Chat tab, the server must be running (`npm run agui`, port 8090) and
   the app needs a plain-HTTP exception in Info.plist:

```xml
<key>NSAppTransportSecurity</key>
<dict><key>NSAllowsLocalNetworking</key><true/></dict>
```

`localhost` reaches the host Mac from the simulator. On a physical device use
the Mac's LAN address instead.

**Try the Fixtures tab first.** It renders committed payloads with no server, no
API key and no network — if something looks wrong there, it is a renderer bug,
not a server or connectivity problem.

## Adding components

This is the extension point. The catalog maps a wire name to a SwiftUI view; a
design system with prefixed type names reconciles here and nowhere else.

```swift
var vds = A2UICatalog()

// Closure form — quickest.
vds.register("Button") { context in
    VDSButton(context.textContent ?? "", kind: context.enumValue("kind") ?? .primary) {
        context.performAction()
    }
}

// Type form — when a component needs real structure.
struct VDSBadgeComponent: A2UIComponent {
    static let a2uiName = "Badge"          // the WIRE name, not the Swift name
    let context: A2UIComponentContext
    init(context: A2UIComponentContext) { self.context = context }
    var body: some View { VDSBadge(text: context.textContent ?? "") }
}
vds.register(VDSBadgeComponent.self)

// Later registrations win, so anything unmapped keeps its built-in stand-in.
let catalog = A2UICatalog.standard.overlaying(vds)
```

A component the catalog doesn't know renders a visible red placeholder naming
it. That is deliberate: the payload is platform-neutral, so the generator can
emit something iOS hasn't mapped yet, and you want to see which name it was.

### Reading properties

`A2UIComponentContext` hands you resolved values — bindings are already
followed, including bindings nested inside a prop object.

| Need | Call |
| --- | --- |
| Text / number / bool prop | `context.string("label")`, `.bool("disabled")`, `.int("max")` |
| String-backed DS enum | `context.enumValue("kind", as: VDSButtonKind.self)` |
| Two-way form state | `context.stringBinding("value")`, `.boolBinding("checked")` |
| Literal child text | `context.textContent` |
| Child views | `context.childrenView()` |
| Fire the action | `context.performAction()` |
| Raw, unresolved value | `context.raw("value")` |

`stringBinding` / `boolBinding` return `nil` when the property is a static
value rather than a binding — render read-only in that case rather than
dropping the user's edits.

### Adding renderer functions

`action.functionCall` is handled locally. `setData`, `toggleData` and `openUrl`
ship by default — they are exactly what `src/systemPrompt.js` promises the
model. Add your own the same way:

```swift
dispatcher.register("hapticTap") { args, _ in
    UIImpactFeedbackGenerator(style: .light).impactOccurred()
}
```

Teaching the model a new function means changing the prompt too, server-side.

## Things that will bite you

These are ported from bugs the React renderer already hit. The tests in
`Tests/A2UICoreTests/GoldenFixtureTests.swift` pin each one.

- **`children` means four different things** — a template `{path, componentId}`,
  an array of component ids, a single component id, or literal text. A bare
  string is a reference *only if it names a component on the surface*; otherwise
  it is text. Get this wrong and every button renders blank.
- **Give each turn its own surface id.** The generator always names its surface
  `"main"`. In a transcript, use `A2UIMessageProcessor.rewritingSurfaceId` or
  every earlier bubble re-renders the newest UI.
- **Bindings nest inside props.** `title: { children: { path: "name" } }` is
  normal. Always read through `context.resolved`/`string`, never `raw`.
- **`checks` is a sibling of `action`**, not nested inside it.
- **Components arrive in any order.** The list is flat and a template may be
  declared before the root that uses it — index by id, then walk from `"root"`.
- **Relative pointers** (`{ path: "name" }`, no leading slash) resolve against
  the row's base path inside a list template.

## What is not built

- **`userAction` round-trip.** `dispatcher.onEvent` gives you the resolved event,
  but the server has no endpoint to receive it yet — that is Phase 5 in
  `A2UI-BACKEND-ARCHITECTURE.md`, and it should be built once, for both clients.
- **Theme.** `createSurface.theme` is parsed but ignored.
- **Most of the catalog.** Ten components have stand-ins; the design system has
  ~35. Unmapped names render the placeholder.
