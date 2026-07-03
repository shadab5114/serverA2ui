# A2UI v0.9 envelope rules

Verified against the a2ui.org v0.9 spec. The renderer rejects payloads that deviate.

## Message envelope

- Top-level wrapper: `{ "a2ui": [ <message>, ... ] }`.
- Every message has `"version": "v0.9"` and **exactly one** other key:
  `createSurface`, `updateDataModel`, or `updateComponents`.
- Typical order: `createSurface`, then `updateDataModel`, then `updateComponents`.

## createSurface

`{ "surfaceId": "<id>", "catalogId": "<catalogId from catalog.json>" }`
— there is **no** `root` field here.

## updateDataModel

`{ "surfaceId": "<id>", "path": "<JSON Pointer>", "value": <any> }`
- `path` is a JSON Pointer; `"/"` replaces the whole model. The key is `value`, not `contents`.

## updateComponents

`{ "surfaceId": "<id>", "components": [ ... ] }`
- Flat list; exactly **one** component has `"id": "root"`.
- Each component: `"id"`, `"component"` (the catalog type name), and its props **inline** —
  no `componentType` / `properties` / `bindings` wrappers.

## Dynamic values (data binding)

A bound value is an inline object `{ "path": "/json/pointer" }` — always JSON Pointer
syntax (`/user/phone`, `/shoes/0/name`), never dot/bracket paths.

## Children

- Static children: a list of component ids, e.g. `"children": ["lockup", "cta"]`.
- List template (collections): `"children": { "path": "/shoes", "componentId": "shoeTile" }`
  plus one template component whose bindings use **relative** pointers
  (`{ "path": "name" }` resolves against each array item).

## Object-shaped props

Some catalog props are objects, e.g. a Tilelet title is
`"title": { "children": "Some text" }` (where the inner value is a DynamicString — a
literal string or a `{ "path": ... }` binding). Always check the component's schema via
`list-components.mjs <Name>` rather than guessing prop shapes.

## Skeleton example

Structural illustration only — verify every component name and prop against the catalog
before use:

```json
{
  "a2ui": [
    { "version": "v0.9",
      "createSurface": { "surfaceId": "main", "catalogId": "<from catalog.json>" } },
    { "version": "v0.9",
      "updateDataModel": { "surfaceId": "main", "path": "/",
        "value": { "user": { "name": "Sidney", "phone": "111-111-1111" } } } },
    { "version": "v0.9",
      "updateComponents": { "surfaceId": "main", "components": [
        { "id": "root", "component": "TileContainer", "children": ["headline", "cta"] },
        { "id": "headline", "component": "Text", "children": { "path": "/user/name" } },
        { "id": "cta", "component": "Button", "children": "Activate now", "kind": "primary" }
      ] } }
  ]
}
```
