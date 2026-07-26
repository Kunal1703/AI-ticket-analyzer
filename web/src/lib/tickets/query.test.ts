import { describe, expect, it } from "vitest";

import {
  buildTicketsHref,
  DEFAULT_LIMIT,
  DEFAULT_SORT,
  hasActiveFilters,
  parseTicketListParams,
} from "./query";

describe("parseTicketListParams", () => {
  it("applies defaults for empty input", () => {
    expect(parseTicketListParams({})).toEqual({
      limit: DEFAULT_LIMIT,
      offset: 0,
      category: undefined,
      priority: undefined,
      status: undefined,
      assignee: undefined,
      source: undefined,
      search: undefined,
      sort: DEFAULT_SORT,
    });
  });

  it("clamps limit to 1–100 and offset to ≥ 0", () => {
    expect(parseTicketListParams({ limit: "999", offset: "-5" }).limit).toBe(100);
    expect(parseTicketListParams({ limit: "0" }).limit).toBe(1);
    expect(parseTicketListParams({ offset: "-5" }).offset).toBe(0);
  });

  it("only forwards recognized enum values (category/priority/status/sort)", () => {
    expect(parseTicketListParams({ category: "Billing" }).category).toBe("Billing");
    expect(parseTicketListParams({ category: "Nonsense" }).category).toBeUndefined();
    expect(parseTicketListParams({ status: "in_progress" }).status).toBe("in_progress");
    expect(parseTicketListParams({ status: "bogus" }).status).toBeUndefined();
    expect(parseTicketListParams({ sort: "created_at" }).sort).toBe("created_at");
    expect(parseTicketListParams({ sort: "weird" }).sort).toBe(DEFAULT_SORT);
  });

  it("trims free-text filters and drops empties", () => {
    expect(parseTicketListParams({ assignee: "  alice " }).assignee).toBe("alice");
    expect(parseTicketListParams({ search: "  " }).search).toBeUndefined();
    expect(parseTicketListParams({ source: "email" }).source).toBe("email");
  });

  it("takes the first value when a param repeats", () => {
    expect(parseTicketListParams({ category: ["Refund", "Billing"] }).category).toBe("Refund");
  });
});

describe("buildTicketsHref", () => {
  it("omits defaults and empty filters", () => {
    expect(buildTicketsHref({ limit: DEFAULT_LIMIT, offset: 0, sort: DEFAULT_SORT })).toBe("/tickets");
  });

  it("serializes filters, sort, and non-default pagination", () => {
    expect(buildTicketsHref({ status: "resolved", offset: 20, limit: DEFAULT_LIMIT })).toBe(
      "/tickets?status=resolved&offset=20",
    );
    expect(buildTicketsHref({ search: "refund", sort: "created_at" })).toBe(
      "/tickets?search=refund&sort=created_at",
    );
  });
});

describe("hasActiveFilters", () => {
  const base = { limit: DEFAULT_LIMIT, offset: 0, sort: DEFAULT_SORT };
  it("ignores pagination and sort", () => {
    expect(hasActiveFilters(base)).toBe(false);
  });
  it("detects any real filter", () => {
    expect(hasActiveFilters({ ...base, status: "open" })).toBe(true);
    expect(hasActiveFilters({ ...base, assignee: "alice" })).toBe(true);
  });
});
