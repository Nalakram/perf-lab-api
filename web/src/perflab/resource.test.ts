import { describe, expect, it, vi } from "vitest";
import {
  initialResource,
  isStale,
  reduceResource,
  resourceData,
  selectResourceBranch,
  toResourceError,
  type AuthedResource,
} from "./resource";

type Rows = string[];
type R = AuthedResource<Rows>;

const err = { message: "boom" };
const success = (data: Rows): R => ({ status: "success", data, refresh: { status: "idle" } });

describe("initialResource", () => {
  it("starts a token-less resource as guest", () => {
    expect(initialResource(false)).toEqual({ status: "guest" });
  });

  it("starts a token-bearing resource as loading, never as empty success", () => {
    expect(initialResource(true)).toEqual({ status: "loading" });
  });
});

describe("reduceResource — availability", () => {
  it("signing out drops any payload", () => {
    expect(reduceResource(success(["a"]), { type: "signed-out" })).toEqual({ status: "guest" });
  });

  it("an identity change discards the previous user's payload", () => {
    expect(reduceResource(success(["a"]), { type: "identity-changed" })).toEqual({ status: "loading" });
  });

  it("a first load resolves to success with an idle refresh", () => {
    const next = reduceResource<Rows, typeof err>({ status: "loading" }, { type: "request-succeeded", data: ["a"] });
    expect(next).toEqual({ status: "success", data: ["a"], refresh: { status: "idle" } });
  });

  it("a first load failure is a top-level error, because no payload exists", () => {
    const next = reduceResource<Rows, typeof err>({ status: "loading" }, { type: "request-failed", error: err });
    expect(next).toEqual({ status: "error", error: err });
  });
});

describe("reduceResource — refresh over a usable payload", () => {
  it("a same-identity refetch keeps the previous data on screen", () => {
    const next = reduceResource(success(["a"]), { type: "request-started" });
    expect(next).toEqual({ status: "success", data: ["a"], refresh: { status: "loading" } });
  });

  it("a successful refresh replaces the data and clears the refresh state", () => {
    const refreshing = reduceResource(success(["a"]), { type: "request-started" });
    expect(reduceResource(refreshing, { type: "request-succeeded", data: ["b"] })).toEqual({
      status: "success",
      data: ["b"],
      refresh: { status: "idle" },
    });
  });

  it("a FAILED refresh keeps the previous data and records the failure", () => {
    const refreshing = reduceResource<Rows, typeof err>(success(["a"]), { type: "request-started" });
    const next = reduceResource(refreshing, { type: "request-failed", error: err });
    expect(next).toEqual({ status: "success", data: ["a"], refresh: { status: "error", error: err } });
    expect(isStale(next)).toBe(true);
  });

  it("a request that starts with no payload yet stays top-level loading", () => {
    expect(reduceResource<Rows, typeof err>({ status: "guest" }, { type: "request-started" })).toEqual({
      status: "loading",
    });
    expect(reduceResource<Rows, typeof err>({ status: "error", error: err }, { type: "request-started" })).toEqual({
      status: "loading",
    });
  });
});

describe("selectResourceBranch", () => {
  const isEmpty = (rows: Rows) => rows.length === 0;

  it("follows the fixed branch order", () => {
    expect(selectResourceBranch<Rows, typeof err>({ status: "guest" }, isEmpty)).toEqual({ kind: "guest" });
    expect(selectResourceBranch<Rows, typeof err>({ status: "loading" }, isEmpty)).toEqual({ kind: "loading" });
    expect(selectResourceBranch<Rows, typeof err>({ status: "error", error: err }, isEmpty)).toEqual({
      kind: "error",
      error: err,
    });
    expect(selectResourceBranch(success([]), isEmpty)).toEqual({ kind: "empty", refresh: { status: "idle" } });
    expect(selectResourceBranch(success(["a"]), isEmpty)).toEqual({
      kind: "success",
      data: ["a"],
      refresh: { status: "idle" },
    });
  });

  it("never treats an error as empty", () => {
    const branch = selectResourceBranch<Rows, typeof err>({ status: "error", error: err }, () => true);
    expect(branch.kind).toBe("error");
  });

  it("never treats a guest as empty", () => {
    const branch = selectResourceBranch<Rows, typeof err>({ status: "guest" }, () => true);
    expect(branch.kind).toBe("guest");
  });

  it("only consults isEmpty for successful data", () => {
    const spy = vi.fn(() => true);
    selectResourceBranch<Rows, typeof err>({ status: "guest" }, spy);
    selectResourceBranch<Rows, typeof err>({ status: "loading" }, spy);
    selectResourceBranch<Rows, typeof err>({ status: "error", error: err }, spy);
    expect(spy).not.toHaveBeenCalled();

    selectResourceBranch(success(["a"]), spy);
    expect(spy).toHaveBeenCalledExactlyOnceWith(["a"]);
  });

  it("treats data as present when no isEmpty predicate is supplied", () => {
    expect(selectResourceBranch(success([])).kind).toBe("success");
  });

  it("carries the refresh state through the empty branch", () => {
    const refreshing = reduceResource(success([]), { type: "request-started" });
    expect(selectResourceBranch(refreshing, isEmpty)).toEqual({ kind: "empty", refresh: { status: "loading" } });
  });
});

describe("resourceData", () => {
  it("returns null rather than a fabricated fallback for every non-success state", () => {
    expect(resourceData<Rows, typeof err>({ status: "guest" })).toBeNull();
    expect(resourceData<Rows, typeof err>({ status: "loading" })).toBeNull();
    expect(resourceData<Rows, typeof err>({ status: "error", error: err })).toBeNull();
    expect(resourceData(success(["a"]))).toEqual(["a"]);
  });

  it("still returns the payload while a refresh is failing", () => {
    const stale = reduceResource<Rows, typeof err>(
      reduceResource(success(["a"]), { type: "request-started" }),
      { type: "request-failed", error: err },
    );
    expect(resourceData(stale)).toEqual(["a"]);
  });
});

describe("toResourceError", () => {
  it("keeps a real message", () => {
    expect(toResourceError({ message: "Server exploded" })).toEqual({ message: "Server exploded" });
  });

  it("falls back for shapes with no usable message", () => {
    expect(toResourceError(null)).toEqual({ message: "Failed to load" });
    expect(toResourceError({})).toEqual({ message: "Failed to load" });
    expect(toResourceError({ message: "" })).toEqual({ message: "Failed to load" });
    expect(toResourceError({ message: 42 })).toEqual({ message: "Failed to load" });
  });
});
