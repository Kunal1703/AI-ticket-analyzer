import { defineConfig } from "vitest/config";

/**
 * Unit tests for the Next.js-free pure modules (error-envelope parsing, the
 * open-redirect guard, cookie option builders). Component/e2e tests arrive with
 * the interactive feature screens in later milestones.
 */
export default defineConfig({
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});
