import { defineConfig } from "vite";

// Renderer MUST work when loaded from disk (file://): no web server.
// base './' keeps every asset reference relative; scripts/inline-dist.js
// then inlines JS/CSS into dist/index.html so there are zero external
// refs at all. Absolute leading-/ refs are FORBIDDEN (verified in build).
export default defineConfig({
  base: "./",
  build: {
    assetsInlineLimit: 1024 * 1024,
    emptyOutDir: true,
    outDir: "../dist",
    rollupOptions: { output: { manualChunks: undefined } },
  },
  root: "renderer",
});
