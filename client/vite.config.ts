import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// @pds/core is linked via `npm link`, so:
//  - dedupe react/react-dom so the linked package shares the app's single copy
//  - exclude @pds/core from prebundling (it changes on rebuild of the design system)
//  - allow serving files from outside the project root (the symlinked package)
export default defineConfig({
  plugins: [react()],
  resolve: {
    dedupe: ["react", "react-dom"],
  },
  optimizeDeps: {
    exclude: ["@pds/core"],
  },
  server: {
    port: 5176,
    strictPort: true,
    fs: { strict: false },
  },
});
