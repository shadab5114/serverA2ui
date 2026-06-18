// Loose module declarations so TS doesn't choke on the @a2ui subpath entries
// and the locally-linked @pds/core. Runtime behavior comes from the real
// packages; these just satisfy the type checker for the dev/build flow.
declare module "@a2ui/react/v0_9";
declare module "@a2ui/react/styles";
declare module "@a2ui/web_core/v0_9";
declare module "@pds/core";
declare module "@pds/core/schemas";
declare module "@pds/core/styles.css";
