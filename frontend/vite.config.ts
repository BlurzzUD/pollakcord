import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

const backend = process.env.POLLAKCORD_BACKEND ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: backend, ws: true, changeOrigin: false },
      "/media": { target: backend, changeOrigin: false },
    },
  },
  build: { sourcemap: false, target: "es2022", chunkSizeWarningLimit: 700 },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: false,
  },
});
