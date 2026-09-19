"""Layout components borrowed from the A2UI basic catalog (reference: src/basicLayoutCatalog.js).

The pds design system has no generic stack/row/list container, so generation
falls back to these standard layout primitives. Their schemas use the same
JSON-Schema dialect as the design-system catalog, so they drop straight into the
{components, $defs} block the system prompt renders.

Copied VERBATIM from the Node source (src/basicLayoutCatalog.js, now in git
history); the prompt snapshot test depends on it. Their
$refs point at https://a2ui.org/.../common_types.json: they are NOT schema-
validated (the gate reports them as unknownComponents, like Node) and that URL
is never fetched. Names must stay in sync with FALLBACK_LAYOUT in
client/src/pdsCatalog.tsx.
"""

from __future__ import annotations

from typing import Any

BASIC_LAYOUT_COMPONENTS: dict[str, Any] = {
    "Column": {
        "type": "object",
        "description": "Layout container: arranges its children VERTICALLY and adds spacing (a gap) between them. Use this to stack components (e.g. a form's fields and its submit button). The design-system components do NOT space their children, so wrap groups in a Column.",
        "allOf": [
            {
                "$ref": "https://a2ui.org/specification/v0_9/common_types.json#/$defs/ComponentCommon"
            },
            {
                "type": "object",
                "properties": {
                    "component": {
                        "const": "Column"
                    },
                    "children": {
                        "$ref": "https://a2ui.org/specification/v0_9/common_types.json#/$defs/ChildList",
                        "description": "An ARRAY of child component ids ([\"id1\",\"id2\"]) for a fixed set, or a { \"path\", \"componentId\" } template for a data list."
                    },
                    "justify": {
                        "type": "string",
                        "enum": [
                            "start",
                            "center",
                            "end",
                            "spaceBetween",
                            "spaceAround",
                            "spaceEvenly",
                            "stretch"
                        ],
                        "default": "start",
                        "description": "Distribution of children along the main (vertical) axis."
                    },
                    "align": {
                        "type": "string",
                        "enum": [
                            "start",
                            "center",
                            "end",
                            "stretch"
                        ],
                        "default": "stretch",
                        "description": "Alignment of children along the cross (horizontal) axis."
                    }
                },
                "required": [
                    "component",
                    "children"
                ]
            }
        ]
    },
    "Row": {
        "type": "object",
        "description": "Layout container: arranges its children HORIZONTALLY and adds spacing (a gap) between them. Use for side-by-side content or a row of buttons.",
        "allOf": [
            {
                "$ref": "https://a2ui.org/specification/v0_9/common_types.json#/$defs/ComponentCommon"
            },
            {
                "type": "object",
                "properties": {
                    "component": {
                        "const": "Row"
                    },
                    "children": {
                        "$ref": "https://a2ui.org/specification/v0_9/common_types.json#/$defs/ChildList",
                        "description": "An ARRAY of child component ids ([\"id1\",\"id2\"]) for a fixed set, or a { \"path\", \"componentId\" } template for a data list."
                    },
                    "justify": {
                        "type": "string",
                        "enum": [
                            "start",
                            "center",
                            "end",
                            "spaceBetween",
                            "spaceAround",
                            "spaceEvenly",
                            "stretch"
                        ],
                        "default": "start",
                        "description": "Distribution of children along the main (horizontal) axis."
                    },
                    "align": {
                        "type": "string",
                        "enum": [
                            "start",
                            "center",
                            "end",
                            "stretch"
                        ],
                        "default": "stretch",
                        "description": "Alignment of children along the cross (vertical) axis."
                    }
                },
                "required": [
                    "component",
                    "children"
                ]
            }
        ]
    },
    "List": {
        "type": "object",
        "description": "Layout container: a scrollable list of children with spacing between them. Prefer Column for simple stacks; use List for long/scrolling collections.",
        "allOf": [
            {
                "$ref": "https://a2ui.org/specification/v0_9/common_types.json#/$defs/ComponentCommon"
            },
            {
                "type": "object",
                "properties": {
                    "component": {
                        "const": "List"
                    },
                    "children": {
                        "$ref": "https://a2ui.org/specification/v0_9/common_types.json#/$defs/ChildList",
                        "description": "An ARRAY of child component ids, or a { \"path\", \"componentId\" } template for a data list."
                    },
                    "direction": {
                        "type": "string",
                        "enum": [
                            "vertical",
                            "horizontal"
                        ],
                        "default": "vertical",
                        "description": "Scroll/stack direction."
                    },
                    "align": {
                        "type": "string",
                        "enum": [
                            "start",
                            "center",
                            "end",
                            "stretch"
                        ],
                        "default": "stretch",
                        "description": "Alignment of children along the cross axis."
                    }
                },
                "required": [
                    "component",
                    "children"
                ]
            }
        ]
    },
    "Divider": {
        "type": "object",
        "description": "A thin separator line between sections. Has NO children.",
        "allOf": [
            {
                "$ref": "https://a2ui.org/specification/v0_9/common_types.json#/$defs/ComponentCommon"
            },
            {
                "type": "object",
                "properties": {
                    "component": {
                        "const": "Divider"
                    },
                    "axis": {
                        "type": "string",
                        "enum": [
                            "horizontal",
                            "vertical"
                        ],
                        "default": "horizontal",
                        "description": "Orientation of the separator line."
                    }
                },
                "required": [
                    "component"
                ]
            }
        ]
    }
}


def merge_basic_layout(catalog: dict[str, Any]) -> dict[str, Any]:
    """Merge the layout components into a catalog IN PLACE (the design system wins
    on any name collision). Returns the same catalog for convenience."""
    components = catalog.setdefault("components", {})
    names = catalog.setdefault("names", list(components))
    for name, schema in BASIC_LAYOUT_COMPONENTS.items():
        if name in components:
            continue  # design system wins
        components[name] = schema
        if name not in names:
            names.append(name)
    return catalog
