import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import path from "node:path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "src") },
  },
  server: {
    port: 5173,
    // Proxy the API in dev so the browser sees one origin and CORS never
    // enters the picture. In production FastAPI serves web/dist itself, so
    // the same relative /api paths keep working with no build-time switch.
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
    rollupOptions: {
      output: {
        // Keep the heavy visual libraries out of the initial bundle. The tool
        // routes must never pay for the story mode's 3D dependencies.
        // No d3 chunk: the charts are hand-rolled SVG and the scales live in
        // lib/scales.ts, so d3 is not a dependency. It comes back only when the
        // story-mode map needs geoAlbersUsa for a real projection.
        manualChunks: {
          vendor: ["react", "react-dom", "react-router-dom"],
          query: ["@tanstack/react-query"],
          table: ["@tanstack/react-table", "@tanstack/react-virtual"],
        },
      },
    },
  },
});
