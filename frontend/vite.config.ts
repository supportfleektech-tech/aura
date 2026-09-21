import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 5173,
    strictPort: true,
    // Allow the sandboxed live-preview host (and any reverse proxy).
    allowedHosts: true as unknown as string[],
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: false,
        ws: true,
      },
    },
  },
});
