import { describe, expect, it } from "vitest";

import { sanitizeNextPath } from "./navigation";

describe("sanitizeNextPath", () => {
  it("allows same-origin relative paths", () => {
    expect(sanitizeNextPath("/dashboard")).toBe("/dashboard");
    expect(sanitizeNextPath("/tickets/123")).toBe("/tickets/123");
  });

  it("falls back for empty/missing input", () => {
    expect(sanitizeNextPath(null)).toBe("/dashboard");
    expect(sanitizeNextPath(undefined)).toBe("/dashboard");
    expect(sanitizeNextPath("")).toBe("/dashboard");
  });

  it("rejects absolute and protocol-relative URLs (open-redirect guard)", () => {
    expect(sanitizeNextPath("https://evil.example")).toBe("/dashboard");
    expect(sanitizeNextPath("//evil.example")).toBe("/dashboard");
    expect(sanitizeNextPath("/\\evil.example")).toBe("/dashboard");
    expect(sanitizeNextPath("javascript:alert(1)")).toBe("/dashboard");
  });

  it("honors a custom fallback", () => {
    expect(sanitizeNextPath(null, "/login")).toBe("/login");
  });
});
