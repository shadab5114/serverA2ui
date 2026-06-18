/**
 * Builds an A2UI catalog from the @pds/core design system so @a2ui/react can
 * render A2UI JSON that targets the pds components.
 *
 * Why "binderless": @a2ui's generic binder detects A2UI primitives
 * (DataBinding `{path}`, ChildList templates) by inspecting zod-v3 schema
 * internals. The @pds/core schemas are zod v4 and describe component PROPS
 * (e.g. `children: z.any()`), not the A2UI wire unions — so the generic binder
 * can't resolve them. With `createBinderlessComponentImplementation` we resolve
 * values ourselves via the component's context (data bindings, child
 * references, and `{path, componentId}` list templates), then hand clean props
 * to the real pds React component.
 *
 * The per-component zod schema from `@pds/core/schemas` is attached to each
 * catalog entry (`api.schema`) as the component's contract.
 */
import React from "react";
import * as PDS from "@pds/core";
import * as Schemas from "@pds/core/schemas";
import { createBinderlessComponentImplementation } from "@a2ui/react/v0_9";
import { Catalog } from "@a2ui/web_core/v0_9";

/** Catalog name the renderer registers under (surfaces bind to it by id). */
export const CATALOG_NAME = "pds";

/** A2UI component name -> the pds React component that renders it. */
const componentMap: Record<string, React.ElementType> = {
  Button: PDS.Button,
  TextLink: PDS.TextLink,
  TextLinkCaret: PDS.TextLinkCaret,
  ButtonGroup: PDS.ButtonGroup,
  Text: PDS.Text,
  Caret: PDS.Caret,
  DirectionalIcon: PDS.DirectionalIcon,
  Tooltip: PDS.Tooltip,
  Badge: PDS.Badge,
  BadgeIndicator: PDS.BadgeIndicator,
  Image: PDS.Image,
  TileContainer: PDS.TileContainer,
  TitleLockup: PDS.TitleLockup,
  TitleLockupTitle: PDS.TitleLockupTitle,
  TitleLockupSubtitle: PDS.TitleLockupSubtitle,
  TitleLockupEyebrow: PDS.TitleLockupEyebrow,
  ScreenReaderText: PDS.ScreenReaderText,
  Tilelet: PDS.Tilelet,
};

/** Component name -> its zod schema (from @pds/core/schemas, "<Name>Schema"). */
const schemaMap: Record<string, unknown> = {};
for (const [exportName, schema] of Object.entries(Schemas)) {
  if (exportName.endsWith("Schema")) {
    schemaMap[exportName.replace(/Schema$/, "")] = schema;
  }
}

// ---- value-shape helpers --------------------------------------------------

const isObject = (v: any) => v != null && typeof v === "object" && !Array.isArray(v);

/** A2UI data binding: `{ path }` (but not a child template). */
const isBinding = (v: any) => isObject(v) && "path" in v && !("componentId" in v);

/** A2UI child template: `{ componentId, path }` — repeat over a data array. */
const isTemplate = (v: any) => isObject(v) && "componentId" in v && "path" in v;

/** A static child list: an array of id strings or `{ id, basePath }` refs. */
const isChildList = (v: any) =>
  Array.isArray(v) &&
  v.length > 0 &&
  v.every((it) => typeof it === "string" || (isObject(it) && "id" in it));

// ---- value resolution -----------------------------------------------------

/**
 * Resolve a raw A2UI property value into something a React component can use:
 * data bindings -> concrete values, nested objects -> resolved field maps.
 * (Child references are handled separately, per the component's `child` /
 * `children` keys.)
 */
function resolveValue(value: any, dc: any): any {
  if (value == null) return value;
  if (isBinding(value)) {
    try {
      return dc.resolveDynamicValue(value);
    } catch {
      return undefined;
    }
  }
  if (Array.isArray(value)) return value.map((v) => resolveValue(v, dc));
  if (isObject(value)) {
    const out: Record<string, any> = {};
    for (const [k, v] of Object.entries(value)) out[k] = resolveValue(v, dc);
    return out;
  }
  return value; // primitive (string / number / boolean)
}

/** Build the React children node(s) from a `children`/`child` value. */
function resolveChildren(value: any, dc: any, buildChild: any): React.ReactNode {
  // `{ componentId, path }` template -> one child per data-array item.
  if (isTemplate(value)) {
    let arr: any[] = [];
    try {
      arr = dc.resolveDynamicValue({ path: value.path }) || [];
    } catch {
      arr = [];
    }
    if (!Array.isArray(arr)) arr = [];
    const listCtx = dc.nested(value.path);
    return arr.map((_, i) =>
      buildChild(value.componentId, listCtx.nested(String(i)).path)
    );
  }
  // Static list of child ids / refs.
  if (isChildList(value)) {
    return value.map((it: any) =>
      typeof it === "string" ? buildChild(it) : buildChild(it.id, it.basePath)
    );
  }
  return null;
}

// ---- catalog component factory --------------------------------------------

function makeImplementation(name: string) {
  const Component = componentMap[name];
  const schema = schemaMap[name];
  const api = { name, schema: schema as any };

  return createBinderlessComponentImplementation(api as any, ({ context, buildChild }: any) => {
    const raw: Record<string, any> = context?.componentModel?.properties || {};
    const dc = context.dataContext;

    const props: Record<string, any> = {};
    let childrenNode: React.ReactNode = undefined;

    for (const [key, value] of Object.entries(raw)) {
      if (key === "child") {
        // Single child reference (a component id string).
        childrenNode = typeof value === "string" ? buildChild(value) : null;
        continue;
      }
      if (key === "children") {
        // Either child references (list/template) OR text content.
        if (isTemplate(value) || isChildList(value)) {
          childrenNode = resolveChildren(value, dc, buildChild);
        } else {
          childrenNode = resolveValue(value, dc); // text/content
        }
        continue;
      }
      props[key] = resolveValue(value, dc);
    }

    if (!Component) {
      return React.createElement(
        "div",
        { style: { color: "#b00", fontFamily: "monospace" } },
        `Unknown component: ${name}`
      );
    }
    return React.createElement(Component as any, props, childrenNode);
  });
}

/** Build the @pds/core catalog for the @a2ui MessageProcessor. */
export function createPdsCatalog() {
  const implementations = Object.keys(componentMap).map(makeImplementation);
  return new Catalog(CATALOG_NAME, implementations, []);
}

/** Component names this catalog supports (handy for the UI). */
export const supportedComponents = Object.keys(componentMap);
