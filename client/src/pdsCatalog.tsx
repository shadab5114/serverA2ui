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
import * as PDS from "@shadab5114/pds-core";
import * as Schemas from "@shadab5114/pds-core/schemas";
import { createBinderlessComponentImplementation, basicCatalog } from "@a2ui/react/v0_9";
import { Catalog, createFunctionImplementation } from "@a2ui/web_core/v0_9";
import { z } from "zod";

/** Catalog name the renderer registers under (surfaces bind to it by id). */
export const CATALOG_NAME = "pds";

/** A2UI component name -> the pds React component that renders it.
 *  Keys mirror the component names in @shadab5114/pds-core's catalog.json. */
const componentMap: Record<string, React.ElementType> = {
  Button: PDS.Button,
  TextLink: PDS.TextLink,
  TextLinkCaret: PDS.TextLinkCaret,
  ButtonGroup: PDS.ButtonGroup,
  IconButton: PDS.IconButton,
  Text: PDS.Text,
  Caret: PDS.Caret,
  DirectionalIcon: PDS.DirectionalIcon,
  Tooltip: PDS.Tooltip,
  Badge: PDS.Badge,
  BadgeIndicator: PDS.BadgeIndicator,
  Image: PDS.Image,
  TileContainer: PDS.TileContainer,
  ComposableTileContainer: PDS.ComposableTileContainer,
  TitleLockup: PDS.TitleLockup,
  TitleLockupTitle: PDS.TitleLockupTitle,
  TitleLockupSubtitle: PDS.TitleLockupSubtitle,
  TitleLockupEyebrow: PDS.TitleLockupEyebrow,
  ScreenReaderText: PDS.ScreenReaderText,
  Tilelet: PDS.Tilelet,
  Accordion: PDS.Accordion,
  AccordionItem: PDS.AccordionItem,
  InputField: PDS.InputField,
  Checkbox: PDS.Checkbox,
  CheckboxGroup: PDS.CheckboxGroup,
  RadioButton: PDS.RadioButton,
  RadioButtonGroup: PDS.RadioButtonGroup,
  RadioBox: PDS.RadioBox,
  RadioBoxGroup: PDS.RadioBoxGroup,
  Toggle: PDS.Toggle,
  TextArea: PDS.TextArea,
  ListGroup: PDS.ListGroup,
  ListGroupItem: PDS.ListGroupItem,
  Modal: PDS.Modal,
  Notification: PDS.Notification,
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

/** A2UI Action value: has an `event` or `functionCall` (e.g. Modal `onClose`). */
const isAction = (v: any) => isObject(v) && ("functionCall" in v || "event" in v);

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

// ---- interactivity (actions + two-way binding) ----------------------------

/** Components whose action fires on close/dismiss (onClose) rather than click. */
const CLOSE_ACTION = new Set(["Modal", "Notification"]);

/**
 * Two-way-bindable form controls: when the control's state prop is a
 * DataBinding, we render it UNCONTROLLED (defaultValue/defaultChecked) and push
 * each change into the data model. Binderless components don't re-render on data
 * changes, so a controlled `value` would freeze the field; uncontrolled + a
 * write-back keeps typing native AND the model current for later reads.
 */
const TWO_WAY: Record<string, { prop: string; defaultProp: string; read: (arg: any) => any }> = {
  InputField: { prop: "value", defaultProp: "defaultValue", read: (e) => e?.target?.value },
  TextArea: { prop: "value", defaultProp: "defaultValue", read: (e) => e?.target?.value },
  Checkbox: { prop: "checked", defaultProp: "defaultChecked", read: (e) => e?.target?.checked },
  Toggle: { prop: "checked", defaultProp: "defaultChecked", read: (e) => e?.target?.checked },
};

/**
 * Run a component's A2UI action, gated by its sibling `checks`:
 *   - functionCall  -> executed locally via the data context (e.g. `openUrl`).
 *   - event         -> context paths resolved, then dispatched to the agent
 *                      (surfaces on the MessageProcessor's action handler).
 */
function runAction(actionSpec: any, checks: any, context: any, dc: any) {
  if (Array.isArray(checks)) {
    for (const chk of checks) {
      let ok = true;
      try {
        ok = !!dc.resolveDynamicValue(chk?.condition);
      } catch {
        ok = false;
      }
      if (!ok) {
        if (typeof window !== "undefined") window.alert(chk?.message || "Validation failed");
        return; // gate failed — block the action
      }
    }
  }
  try {
    if (actionSpec?.functionCall) {
      dc.resolveDynamicValue(actionSpec.functionCall);
    } else if (actionSpec?.event) {
      context.dispatchAction(dc.resolveAction(actionSpec));
    }
  } catch (err) {
    console.error("[a2ui] action failed:", err);
  }
}

// ---- renderer functions (local FunctionCall handlers) ---------------------

/**
 * Design-system renderer functions callable from `action.functionCall`.
 * `openUrl` (+ validation/logic helpers) already come from the basic catalog;
 * these add local data-model mutation so a UI can drive its own state (open a
 * modal, flip a toggle) with no agent round-trip. `execute(args, ctx)` receives
 * the triggering component's DataContext — `ctx.set(path, value)` writes back
 * into the surface data model (paths are JSON Pointers).
 */
const setDataFn = createFunctionImplementation(
  { name: "setData", returnType: "void", schema: z.object({ path: z.string(), value: z.any() }) } as any,
  (args: any, ctx: any) => {
    ctx.set(args.path, args.value);
  }
);

const toggleDataFn = createFunctionImplementation(
  { name: "toggleData", returnType: "void", schema: z.object({ path: z.string() }) } as any,
  (args: any, ctx: any) => {
    ctx.set(args.path, !ctx.resolveDynamicValue({ path: args.path }));
  }
);

/** DS-provided functions merged on top of the basic catalog's functions. */
const PDS_FUNCTIONS = [setDataFn, toggleDataFn];

// ---- catalog component factory --------------------------------------------

function makeImplementation(name: string) {
  const Component = componentMap[name];
  const schema = schemaMap[name];
  const api = { name, schema: schema as any };

  return createBinderlessComponentImplementation(api as any, ({ context, buildChild }: any) => {
    const raw: Record<string, any> = context?.componentModel?.properties || {};
    const dc = context.dataContext;

    // Re-render this component on ANY data-model change so one-shot resolved
    // bindings (Modal.opened, bound text, an input's value) reflect writes made
    // by setData / dc.set. Binderless components otherwise only re-render on
    // component create/delete, so a bound `opened` flag would never update the
    // Modal. Subscribing to "/" catches every set (each set notifies ancestors
    // up to the root).
    const dataModel = dc.dataModel;
    const store = React.useMemo(() => {
      let version = 0;
      return {
        subscribe: (cb: () => void) => {
          const sub = dataModel.subscribe("/", () => {
            version++;
            cb();
          });
          return () => sub.unsubscribe();
        },
        getSnapshot: () => version,
      };
    }, [dataModel]);
    React.useSyncExternalStore(store.subscribe, store.getSnapshot);

    // Does a string name an actual component on this surface? Used to tell a
    // single child reference (`children: "signup-form"`) apart from text
    // content (`children: "Submit"`).
    const isComponentId = (v: any) =>
      typeof v === "string" && !!context?.surfaceComponents?.get?.(v);

    const props: Record<string, any> = {};
    let childrenNode: React.ReactNode = undefined;
    let actionSpec: any = null;
    let checksSpec: any = null;
    const twoWay = TWO_WAY[name];

    for (const [key, value] of Object.entries(raw)) {
      // Interaction props are handled below, not passed to the pds component.
      if (key === "action") {
        actionSpec = value;
        continue;
      }
      if (key === "checks") {
        checksSpec = value;
        continue;
      }
      // A prop whose VALUE is an Action (e.g. Modal/Notification `onClose`)
      // becomes a handler that runs it — not passed through as an object.
      if (isAction(value)) {
        props[key] = () => runAction(value, null, context, dc);
        continue;
      }
      if (key === "child") {
        // Single child reference (a component id string).
        childrenNode = typeof value === "string" ? buildChild(value) : null;
        continue;
      }
      if (key === "children") {
        // Child references (list / template / single id) OR text content.
        if (isTemplate(value) || isChildList(value)) {
          childrenNode = resolveChildren(value, dc, buildChild);
        } else if (isComponentId(value)) {
          // A single component-id reference, e.g. TileContainer children: "signup-form".
          childrenNode = buildChild(value);
        } else {
          childrenNode = resolveValue(value, dc); // text/content
        }
        continue;
      }
      // Two-way binding: a bound state prop (value/checked) renders uncontrolled
      // and writes each change back to the data model. See TWO_WAY.
      if (twoWay && key === twoWay.prop && isBinding(value)) {
        const bindPath = (value as any).path;
        props[twoWay.defaultProp] = resolveValue(value, dc);
        props.onChange = (arg: any) => {
          try {
            dc.set(bindPath, twoWay.read(arg));
          } catch {
            /* ignore write failures */
          }
        };
        continue;
      }
      props[key] = resolveValue(value, dc);
    }

    // Wire the action to the component's click / close handler.
    if (actionSpec) {
      const handler = CLOSE_ACTION.has(name) ? "onClose" : "onClick";
      props[handler] = () => runAction(actionSpec, checksSpec, context, dc);
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

/** Layout primitives borrowed from the basic A2UI catalog. The pds design
 *  system has no generic stack/row container, so we fall back to these for
 *  spacing/structure; pds components still win on any name overlap.
 *  MUST stay in sync with the server's BASIC_LAYOUT_COMPONENTS keys in
 *  src/basicLayoutCatalog.js (which teaches the LLM the same set). */
const FALLBACK_LAYOUT = ["Column", "Row", "List", "Divider"];

/** Build the merged catalog (pds components + basic-catalog layout) for the
 *  @a2ui MessageProcessor. */
export function createPdsCatalog() {
  const pdsImpls = Object.keys(componentMap).map(makeImplementation);
  const pdsNames = new Set(Object.keys(componentMap));
  const layoutImpls = [...basicCatalog.components.values()].filter(
    (impl: any) => FALLBACK_LAYOUT.includes(impl.name) && !pdsNames.has(impl.name)
  );
  // Basic-catalog functions (openUrl + validation/logic/format) plus our
  // DS-provided data-model mutators (setData / toggleData).
  const functions = [...basicCatalog.functions.values(), ...PDS_FUNCTIONS];
  return new Catalog(CATALOG_NAME, [...pdsImpls, ...layoutImpls], functions as any);
}

/** Component names this catalog supports (handy for the UI). */
export const supportedComponents = [...Object.keys(componentMap), ...FALLBACK_LAYOUT];
