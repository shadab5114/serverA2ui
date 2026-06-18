import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App.tsx";
import "./App.css";

// A2UI base styles (layout primitives, etc.)
import { injectStyles } from "@a2ui/react/styles";
// @pds/core design tokens (CSS custom properties on :root) — MUST load before
// the component styles, which reference 600+ --pdesign-* vars defined here.
import "pdesign-tokens/dist/tokens/index.css";
// @pds/core component styles.
import "@pds/core/styles.css";

injectStyles();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>
);
