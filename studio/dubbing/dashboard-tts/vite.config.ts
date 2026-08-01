import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

// Pird: build of the merged TTS dashboard. Output goes to
// `dist/` so Cloudflare Pages can deploy it as a static site.
//
// base: "/" (the default) makes Vite emit /assets/* paths in
// index.html, matching the build output structure on Cloudflare
// Pages. Previously used "/tts/" when the bundle was served by
// FastAPI's /tts/* static mount, but that path prefix is no
// longer in the deployed filesystem -- CF Pages serves dist/
// files at their literal paths, so /tts/assets/* 404s and the
// SPA returns the HTML 404 page.
export default defineConfig({
  base: "/",
  plugins: [react()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  build: {
    outDir: "dist",
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
