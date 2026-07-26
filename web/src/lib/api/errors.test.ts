import { describe, expect, it } from "vitest";

import { apiErrorFromBody, ApiError, isErrorEnvelope } from "./errors";

describe("isErrorEnvelope", () => {
  it("accepts a well-formed envelope", () => {
    expect(
      isErrorEnvelope({ error: { code: "not_found", message: "nope", request_id: "abc" } }),
    ).toBe(true);
  });

  it("rejects other shapes", () => {
    expect(isErrorEnvelope(null)).toBe(false);
    expect(isErrorEnvelope({ detail: "x" })).toBe(false);
    expect(isErrorEnvelope({ error: { code: 1 } })).toBe(false);
  });
});

describe("apiErrorFromBody", () => {
  it("maps a backend envelope into ApiError", () => {
    const err = apiErrorFromBody(404, {
      error: { code: "not_found", message: "Ticket not found", request_id: "req-1" },
    });
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(404);
    expect(err.code).toBe("not_found");
    expect(err.message).toBe("Ticket not found");
    expect(err.requestId).toBe("req-1");
  });

  it("falls back for unrecognized bodies", () => {
    const err = apiErrorFromBody(500, undefined);
    expect(err.status).toBe(500);
    expect(err.code).toBe("unexpected_error");
    expect(err.requestId).toBeNull();
  });
});
