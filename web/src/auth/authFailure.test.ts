// Pure policy table for "what does a failed session check mean?".
//
// No DOM, no React, no network — this file is the classifier's specification.
// The lifecycle half (does AuthProvider actually honour these decisions, and do
// the sessionStorage keys survive?) is proven in AuthContext.test.tsx.
//
// The invariant under test, stated once: SIGN-OUT IS REACHABLE ONLY FROM A 401.
// Every other input — including inputs we cannot classify — preserves the session.
import { describe, expect, it } from "vitest";

import {
  classifyAuthFailure,
  describeSessionUnavailable,
  isSessionUser,
  MALFORMED_SESSION_RESPONSE,
  type SessionUnavailableReason,
} from "./authFailure";

/** The exact object shape perfLabClient throws (src/api/perfLabClient.ts:116-121). */
function apiError(status: number) {
  return { message: "boom", status, details: undefined };
}

describe("401 — the only failure that may sign an athlete out", () => {
  it("classifies a 401 as sign-out", () => {
    expect(classifyAuthFailure(apiError(401))).toEqual({
      action: "sign-out",
      reason: "session-expired",
      status: 401,
    });
  });

  it("does not need an Error subclass — the thrown value is a plain object", () => {
    // instanceof Error is false for what perfLabClient throws; the classifier
    // must not depend on it.
    expect(apiError(401) instanceof Error).toBe(false);
    expect(classifyAuthFailure(apiError(401)).action).toBe("sign-out");
  });
});

describe("5xx — the server is up but unhealthy (deploy, restart, crash)", () => {
  it.each([500, 502, 503, 504, 599])("preserves the session on %i", (status) => {
    expect(classifyAuthFailure(apiError(status))).toEqual({
      action: "keep-session",
      reason: "server-error",
      status,
    });
  });
});

describe("other 4xx — refused, but not logged out", () => {
  it.each([400, 403, 404, 418, 422, 429])(
    "preserves the session on %i",
    (status) => {
      expect(classifyAuthFailure(apiError(status))).toEqual({
        action: "keep-session",
        reason: "request-rejected",
        status,
      });
    },
  );
});

describe("no status at all — network, CORS, offline, timeout", () => {
  it("classifies a raw fetch TypeError as a network failure", () => {
    // What `await fetch(...)` rejects with when the host is unreachable. It
    // never reaches handleResponse, so it carries no `status` whatsoever.
    const err = new TypeError("Failed to fetch");
    expect("status" in err).toBe(false);
    expect(classifyAuthFailure(err)).toEqual({
      action: "keep-session",
      reason: "network",
      status: null,
    });
  });

  it("preserves the session for an object with no status property", () => {
    expect(classifyAuthFailure({ message: "something went wrong" })).toEqual({
      action: "keep-session",
      reason: "unknown",
      status: null,
    });
  });

  it("preserves the session for a generic Error", () => {
    expect(classifyAuthFailure(new Error("nope"))).toEqual({
      action: "keep-session",
      reason: "unknown",
      status: null,
    });
  });
});

describe("unclassifiable input is never treated as an auth failure", () => {
  it.each([
    ["null", null],
    ["undefined", undefined],
    ["a string", "401"],
    ["a number", 401],
    ["a boolean", false],
    ["an array", [401]],
    ["an empty object", {}],
  ])("preserves the session for %s", (_label, value) => {
    const result = classifyAuthFailure(value);
    expect(result.action).toBe("keep-session");
    expect(result.status).toBeNull();
  });

  it.each([
    ["a string status", { status: "401" }],
    ["a null status", { status: null }],
    ["an object status", { status: { code: 401 } }],
    ["a NaN status", { status: Number.NaN }],
  ])("does not sign out when status is %s", (_label, value) => {
    // A stringly-typed "401" is the classic near-miss: coercing it would sign
    // the athlete out on a shape we never actually produce.
    expect(classifyAuthFailure(value)).toEqual({
      action: "keep-session",
      reason: "unknown",
      status: null,
    });
  });
});

describe("malformed 200 payloads", () => {
  it("is a preserve-the-session outcome", () => {
    expect(MALFORMED_SESSION_RESPONSE).toEqual({
      action: "keep-session",
      reason: "malformed-response",
      status: null,
    });
  });

  it.each([
    ["null", null],
    ["undefined", undefined],
    ["an HTML string", "<html>502 Bad Gateway</html>"],
    ["an empty object", {}],
    ["a numeric email", { id: 1, email: 7 }],
    ["a string id", { id: "1", email: "a@b.c" }],
    ["only an email", { email: "a@b.c" }],
  ])("rejects %s as a session user", (_label, value) => {
    expect(isSessionUser(value)).toBe(false);
  });

  it("accepts a real UserResponse", () => {
    expect(isSessionUser({ id: 1, email: "a@b.c", is_active: true })).toBe(true);
  });
});

describe("athlete-facing copy", () => {
  const reasons: SessionUnavailableReason[] = [
    "server-error",
    "request-rejected",
    "network",
    "malformed-response",
    "unknown",
  ];

  it("has non-empty wording for every reason", () => {
    for (const reason of reasons) {
      expect(describeSessionUnavailable(reason).length).toBeGreaterThan(0);
    }
  });

  it("never tells the athlete they were signed out", () => {
    for (const reason of reasons) {
      expect(describeSessionUnavailable(reason).toLowerCase()).not.toContain(
        "signed out",
      );
    }
  });
});
