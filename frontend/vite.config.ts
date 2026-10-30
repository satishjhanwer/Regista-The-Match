import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// Dev server proxies the FastAPI backend (python -m regista.api on :8000).
const backend = process.env.REGISTA_BACKEND ?? "http://127.0.0.1:8000";

export default defineConfig({
  // GitHub Pages serves a project site under /<repo>/; the static build sets VITE_BASE to that.
  base: process.env.VITE_BASE ?? "/",
  // public/ holds only the static demo's bundle; the normal build is served by FastAPI and does not need it.
  build: { copyPublicDir: process.env.VITE_STATIC === "1" },
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": backend,
      "/ws": { target: backend.replace(/^http/, "ws"), ws: true },
    },
  },
  test: { environment: "node", include: ["src/**/*.test.ts"] },
});
