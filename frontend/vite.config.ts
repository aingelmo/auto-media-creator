import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Built assets are committed to src/edl_agent/web/static/ so the Python
// package ships a working UI with no node/npm install at runtime (see
// AGENTS.md / scripts/run_web.py). Only touch this frontend/ tree when
// editing the UI: `npm run dev` for local iteration (proxied to the FastAPI
// server), `npm run build` to refresh the committed static/ output.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "../src/edl_agent/web/static",
    emptyOutDir: true,
  },
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/sessions": "http://127.0.0.1:8000",
    },
  },
});
