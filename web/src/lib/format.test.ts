import { describe, expect, it } from "vitest";

import { formatDateTime, formatSla, isOverdue } from "./format";

describe("formatDateTime", () => {
  it("renders an ISO timestamp as compact UTC", () => {
    expect(formatDateTime("2026-07-08T13:45:30Z")).toBe("2026-07-08 13:45 UTC");
  });

  it("returns a dash for missing input", () => {
    expect(formatDateTime(null)).toBe("—");
    expect(formatDateTime(undefined)).toBe("—");
  });

  it("passes through unparseable input unchanged", () => {
    expect(formatDateTime("not-a-date")).toBe("not-a-date");
  });
});

describe("formatSla / isOverdue", () => {
  const now = new Date("2026-07-08T12:00:00Z");

  it("flags a past deadline as overdue", () => {
    const past = "2026-07-08T11:00:00Z";
    expect(isOverdue(past, now)).toBe(true);
    expect(formatSla(past, now)).toContain("overdue");
  });

  it("shows a future deadline without the overdue prefix", () => {
    const future = "2026-07-08T18:00:00Z";
    expect(isOverdue(future, now)).toBe(false);
    expect(formatSla(future, now)).toBe("2026-07-08 18:00 UTC");
  });

  it("handles a missing deadline", () => {
    expect(isOverdue(null, now)).toBe(false);
    expect(formatSla(null, now)).toBe("—");
  });
});
