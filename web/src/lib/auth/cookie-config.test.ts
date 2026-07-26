import { describe, expect, it } from "vitest";

import { ACCESS_MAX_AGE, cookieOptions, REFRESH_MAX_AGE } from "./cookie-config";

describe("cookieOptions", () => {
  it("produces httpOnly, lax, root-path options with the given lifetime", () => {
    const opts = cookieOptions(ACCESS_MAX_AGE);
    expect(opts.httpOnly).toBe(true);
    expect(opts.sameSite).toBe("lax");
    expect(opts.path).toBe("/");
    expect(opts.maxAge).toBe(ACCESS_MAX_AGE);
  });

  it("mirrors the backend token TTLs", () => {
    // Keep these in lockstep with app/config.py defaults so a dropped access
    // cookie is a reliable "needs refresh" signal.
    expect(ACCESS_MAX_AGE).toBe(900);
    expect(REFRESH_MAX_AGE).toBe(1_209_600);
  });

  it("is not Secure in the test/development environment", () => {
    // NODE_ENV is 'test' under vitest, so cookies must work over plain http.
    expect(cookieOptions(ACCESS_MAX_AGE).secure).toBe(false);
  });
});
