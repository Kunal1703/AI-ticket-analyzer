import { describe, expect, it } from "vitest";

import {
  barPercent,
  buildAnalyticsHref,
  parseAnalyticsParams,
  sortedEntries,
  validDate,
} from "./query";

describe("validDate", () => {
  it("accepts ISO calendar dates", () => {
    expect(validDate("2026-07-09")).toBe("2026-07-09");
  });
  it("rejects malformed or non-dates", () => {
    expect(validDate(undefined)).toBeUndefined();
    expect(validDate("2026/07/09")).toBeUndefined();
    expect(validDate("2026-13-40")).toBeUndefined();
    expect(validDate("yesterday")).toBeUndefined();
  });
});

describe("parseAnalyticsParams", () => {
  it("defaults metric to tickets and drops bad dates", () => {
    expect(parseAnalyticsParams({})).toEqual({
      metric: "tickets",
      start: undefined,
      end: undefined,
    });
    expect(parseAnalyticsParams({ metric: "bogus", start: "nope" }).metric).toBe("tickets");
  });
  it("honors a valid metric and window", () => {
    const p = parseAnalyticsParams({ metric: "analyses", start: "2026-01-01", end: "2026-02-01" });
    expect(p).toEqual({ metric: "analyses", start: "2026-01-01", end: "2026-02-01" });
  });
  it("takes the first value when a param repeats", () => {
    expect(parseAnalyticsParams({ metric: ["analyses", "tickets"] }).metric).toBe("analyses");
  });
});

describe("buildAnalyticsHref", () => {
  it("omits the default metric and empty window", () => {
    expect(buildAnalyticsHref({ metric: "tickets" })).toBe("/analytics");
  });
  it("serializes metric + window", () => {
    expect(buildAnalyticsHref({ metric: "analyses", start: "2026-01-01" })).toBe(
      "/analytics?metric=analyses&start=2026-01-01",
    );
  });
});

describe("barPercent", () => {
  it("scales against the max and clamps", () => {
    expect(barPercent(5, 10)).toBe(50);
    expect(barPercent(10, 10)).toBe(100);
    expect(barPercent(0, 10)).toBe(0);
  });
  it("returns 0 for a non-positive max", () => {
    expect(barPercent(3, 0)).toBe(0);
  });
});

describe("sortedEntries", () => {
  it("sorts by count descending", () => {
    expect(sortedEntries({ a: 1, b: 5, c: 3 })).toEqual([
      ["b", 5],
      ["c", 3],
      ["a", 1],
    ]);
  });
});
