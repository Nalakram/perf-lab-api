import path from "node:path";
import { defineConfig } from "vitest/config";

// Node stays the DEFAULT environment: the pure suites (unit conversion, state
// reductions, resource transitions) touch no DOM and must not pay for browser
// emulation. The few React hook/component tests opt in per file with a
// `// @vitest-environment jsdom` docblock — see useAuthedResource.test.tsx.
export default defineConfig({
  test: {
    environment: "node",
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
});
