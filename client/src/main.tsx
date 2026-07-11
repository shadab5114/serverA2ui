import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App.tsx";
import "./App.css";

// A2UI base styles (layout primitives, etc.)
import { injectStyles } from "@a2ui/react/styles";
// @shadab5114/pds-core design tokens (CSS custom properties on :root) — MUST
// load before the component styles, which reference the --pdesign-* vars here.
import "@shadab5114/pdesign-tokens/index.css";
// @shadab5114/pds-core component styles.
import "@shadab5114/pds-core/styles.css";

injectStyles();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>
);
