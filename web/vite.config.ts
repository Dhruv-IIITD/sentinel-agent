import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The app is served by FastAPI under /ui, so assets must resolve relative to it.
// In `npm run dev`, API calls are proxied to the backend on :8000.
const API = "http://localhost:8000";
const proxied = ["/approvals", "/audit", "/chat", "/threads", "/compensate", "/voice", "/healthz"];

export default defineConfig({
  plugins: [react()],
  base: "/ui/",
  build: { outDir: "dist", emptyOutDir: true },
  server: {
    proxy: Object.fromEntries(proxied.map((p) => [p, { target: API, changeOrigin: true }])),
  },
});
