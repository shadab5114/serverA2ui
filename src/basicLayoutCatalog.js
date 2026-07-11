/**
 * Layout components borrowed from the A2UI **basic catalog** and merged into the
 * design-system catalog for generation.
 *
 * The pds design system has no generic stack/row/list container, so we fall back
 * to these standard layout primitives. Their schemas are expressed in the SAME
 * JSON-Schema dialect the design-system catalog uses (an `allOf` of the shared
 * `common_types.json#/$defs/ComponentCommon` plus an inline properties object,
 * with children typed as the shared `ChildList`) so they drop straight into the
 * `{ components, $defs }` block the system prompt renders — no special-casing.
 *
 * Source of truth for prop names / enums:
 *   https://a2ui.org/specification/v0_9/catalogs/basic/catalog.json
 * The names here MUST stay in sync with the client's FALLBACK_LAYOUT list in
 * client/src/pdsCatalog.tsx, which registers the matching React implementations.
 */

const COMMON = "https://a2ui.org/specification/v0_9/common_types.json";

/** The basic-catalog layout components we expose (name -> JSON-Schema). */
export const BASIC_LAYOUT_COMPONENTS = {
  Column: {
    type: "object",
    description:
      "Layout container: arranges its children VERTICALLY and adds spacing (a gap) between them. Use this to stack components (e.g. a form's fields and its submit button). The design-system components do NOT space their children, so wrap groups in a Column.",
    allOf: [
      { $ref: `${COMMON}#/$defs/ComponentCommon` },
      {
        type: "object",
        properties: {
          component: { const: "Column" },
          children: {
            $ref: `${COMMON}#/$defs/ChildList`,
            description:
              'An ARRAY of child component ids (["id1","id2"]) for a fixed set, or a { "path", "componentId" } template for a data list.',
          },
          justify: {
            type: "string",
            enum: ["start", "center", "end", "spaceBetween", "spaceAround", "spaceEvenly", "stretch"],
            default: "start",
            description: "Distribution of children along the main (vertical) axis.",
          },
          align: {
            type: "string",
            enum: ["start", "center", "end", "stretch"],
            default: "stretch",
            description: "Alignment of children along the cross (horizontal) axis.",
          },
        },
        required: ["component", "children"],
      },
    ],
  },

  Row: {
    type: "object",
    description:
      "Layout container: arranges its children HORIZONTALLY and adds spacing (a gap) between them. Use for side-by-side content or a row of buttons.",
    allOf: [
      { $ref: `${COMMON}#/$defs/ComponentCommon` },
      {
        type: "object",
        properties: {
          component: { const: "Row" },
          children: {
            $ref: `${COMMON}#/$defs/ChildList`,
            description:
              'An ARRAY of child component ids (["id1","id2"]) for a fixed set, or a { "path", "componentId" } template for a data list.',
          },
          justify: {
            type: "string",
            enum: ["start", "center", "end", "spaceBetween", "spaceAround", "spaceEvenly", "stretch"],
            default: "start",
            description: "Distribution of children along the main (horizontal) axis.",
          },
          align: {
            type: "string",
            enum: ["start", "center", "end", "stretch"],
            default: "stretch",
            description: "Alignment of children along the cross (vertical) axis.",
          },
        },
        required: ["component", "children"],
      },
    ],
  },

  List: {
    type: "object",
    description:
      "Layout container: a scrollable list of children with spacing between them. Prefer Column for simple stacks; use List for long/scrolling collections.",
    allOf: [
      { $ref: `${COMMON}#/$defs/ComponentCommon` },
      {
        type: "object",
        properties: {
          component: { const: "List" },
          children: {
            $ref: `${COMMON}#/$defs/ChildList`,
            description:
              'An ARRAY of child component ids, or a { "path", "componentId" } template for a data list.',
          },
          direction: {
            type: "string",
            enum: ["vertical", "horizontal"],
            default: "vertical",
            description: "Scroll/stack direction.",
          },
          align: {
            type: "string",
            enum: ["start", "center", "end", "stretch"],
            default: "stretch",
            description: "Alignment of children along the cross axis.",
          },
        },
        required: ["component", "children"],
      },
    ],
  },

  Divider: {
    type: "object",
    description: "A thin separator line between sections. Has NO children.",
    allOf: [
      { $ref: `${COMMON}#/$defs/ComponentCommon` },
      {
        type: "object",
        properties: {
          component: { const: "Divider" },
          axis: {
            type: "string",
            enum: ["horizontal", "vertical"],
            default: "horizontal",
            description: "Orientation of the separator line.",
          },
        },
        required: ["component"],
      },
    ],
  },
};

/**
 * Merge the borrowed layout components into a fetched catalog IN PLACE.
 * The design system wins on any name collision (its components are never
 * overwritten). Returns the same catalog for convenience.
 *
 * @param {{ components: Record<string, any>, defs?: object, names?: string[] }} catalog
 */
export function mergeBasicLayout(catalog) {
  if (!catalog || typeof catalog !== "object") return catalog;
  catalog.components = catalog.components || {};
  catalog.names = catalog.names || Object.keys(catalog.components);
  for (const [name, schema] of Object.entries(BASIC_LAYOUT_COMPONENTS)) {
    if (catalog.components[name]) continue; // design system wins
    catalog.components[name] = schema;
    if (!catalog.names.includes(name)) catalog.names.push(name);
  }
  return catalog;
}
