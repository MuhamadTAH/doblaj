import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

// Pird: build of the merged TTS dashboard. Output goes to
// dubbing/app/static/tts-dashboard/ so FastAPI can serve it as
// StaticFiles(html=True) at /tts/*. dev-mode proxy points at
// the merged dubbing service on :8002 (was :8000 in standalone
// tts-service_old).
//
// base: "/tts/" makes Vite emit /tts/assets/* paths in index.html
// (instead of /assets/*). Required because the bundle is mounted
// at /tts/, not at the domain root. Without this the browser sees
// 404s for the JS/CSS chunks.
export default defineConfig({
  base: "/tts/",
  plugins: [react()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  build: {
    outDir: path.resolve(__dirname, "../app/static/tts-dashboard"),
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8002",
        changeOrigin: true,
      },
      "/video": {
        target: "http://localhost:8002",
        changeOrigin: true,
      },
      "/static": {
        target: "http://localhost:8002",
        changeOrigin: true,
      },
    },
  },
});
