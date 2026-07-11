// Loose module declarations so TS doesn't choke on the @a2ui subpath entries
// and the CSS side-effect imports. @shadab5114/pds-core ships real types, so it
// is intentionally NOT stubbed here — we type-check against the real package.
declare module "@a2ui/react/v0_9";
declare module "@a2ui/react/styles";
declare module "@a2ui/web_core/v0_9";
declare module "@shadab5114/pds-core/styles.css";
declare module "@shadab5114/pdesign-tokens/index.css";
