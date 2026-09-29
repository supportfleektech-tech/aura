import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    setupFiles: ["./src/setupTests.ts"],
    // Heavy component renders (SettingsView fans out to ~8 mocked endpoints) can
    // exceed the 5s default on a loaded machine and fail spuriously.
    testTimeout: 20000,
    hookTimeout: 20000,
  },
});
