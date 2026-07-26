import { describe, expect, it } from "vitest";

import { buildRoutingActions, buildRoutingConditions, parseCsvList } from "./parse";

describe("parseCsvList", () => {
  it("splits, trims, and drops empties", () => {
    expect(parseCsvList("a, b ,, c")).toEqual(["a", "b", "c"]);
  });
  it("de-duplicates", () => {
    expect(parseCsvList("x, x, y")).toEqual(["x", "y"]);
  });
  it("handles empty/missing input", () => {
    expect(parseCsvList("")).toEqual([]);
    expect(parseCsvList(null)).toEqual([]);
    expect(parseCsvList(undefined)).toEqual([]);
  });
});

describe("buildRoutingConditions", () => {
  it("includes only present keys", () => {
    expect(buildRoutingConditions("Billing", null)).toEqual({ category: "Billing" });
    expect(buildRoutingConditions("Billing", "High")).toEqual({
      category: "Billing",
      priority: "High",
    });
    expect(buildRoutingConditions("", "")).toEqual({});
  });
});

describe("buildRoutingActions", () => {
  it("always includes tags and omits an empty assignee", () => {
    expect(buildRoutingActions("", "vip, urgent")).toEqual({ tags: ["vip", "urgent"] });
    expect(buildRoutingActions("alice", "")).toEqual({ tags: [], assignee: "alice" });
  });
});
