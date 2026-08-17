import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// @shadab5114/pds-core is a normal installed dependency now, so we only need to
// dedupe react/react-dom so it shares the app's single React copy.
export default defineConfig({
  plugins: [react()],
  resolve: {
    dedupe: ["react", "react-dom"],
  },
  server: {
    port: 5176,
    strictPort: true,
    fs: { strict: false },
    // Proxy /generate (and /health) to the A2UI generation server so the client
    // can call it same-origin and avoid CORS. Override the target with API_TARGET.
    proxy: {
      "/generate": { target: process.env.API_TARGET || "http://localhost:8080", changeOrigin: true },
      "/health": { target: process.env.API_TARGET || "http://localhost:8080", changeOrigin: true },
      // Phase 3: AG-UI SSE endpoint (LangGraph chat) on the agui server.
      "/agui": { target: process.env.AGUI_TARGET || "http://localhost:8090", changeOrigin: true },
    },
  },
});
