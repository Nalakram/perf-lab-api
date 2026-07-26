// @vitest-environment jsdom
//
// The shared honesty boundary. These assertions are the reason the component
// exists: a screen cannot select its own branch, so it cannot render an error as
// "you have nothing yet", cannot forget the guest branch, and cannot flash an
// empty state while a first load is in flight.
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ResourceState } from "./ResourceState";
import type { AuthedResource } from "./resource";

afterEach(cleanup);

type Rows = string[];

const success = (data: Rows, refresh: "idle" | "loading" | "error" = "idle"): AuthedResource<Rows> => ({
  status: "success",
  data,
  refresh: refresh === "error" ? { status: "error", error: { message: "Refresh failed" } } : { status: refresh },
});

function renderState(resource: AuthedResource<Rows>, overrides: Partial<Parameters<typeof ResourceState<Rows>>[0]> = {}) {
  return render(
    <ResourceState<Rows>
      resource={resource}
      isEmpty={(rows) => rows.length === 0}
      guest={{ title: "Sign in to view your history" }}
      empty={{ title: "No sessions yet" }}
      error={{ title: "History unavailable" }}
      {...overrides}
    >
      {(rows) => <ul>{rows.map((r) => <li key={r}>{r}</li>)}</ul>}
    </ResourceState>,
  );
}

describe("branch selection", () => {
  it("renders the guest state, not an empty state", () => {
    renderState({ status: "guest" });
    expect(screen.getByText("Sign in to view your history")).toBeDefined();
    expect(screen.queryByText("No sessions yet")).toBeNull();
  });

  it("renders loading, not empty, during a first load", () => {
    renderState({ status: "loading" });
    expect(screen.getByRole("status")).toBeDefined();
    expect(screen.queryByText("No sessions yet")).toBeNull();
  });

  it("renders an error as an error, never as empty", () => {
    renderState({ status: "error", error: { message: "Server exploded" } });
    expect(screen.getByText("History unavailable")).toBeDefined();
    expect(screen.getByText("Server exploded")).toBeDefined();
    expect(screen.queryByText("No sessions yet")).toBeNull();
  });

  it("renders the empty state for successful empty data", () => {
    renderState(success([]));
    expect(screen.getByText("No sessions yet")).toBeDefined();
  });

  it("renders children for successful non-empty data", () => {
    renderState(success(["Monday"]));
    expect(screen.getByText("Monday")).toBeDefined();
  });

  it("treats successful data as present when no isEmpty predicate is given", () => {
    renderState(success([]), { isEmpty: undefined });
    expect(screen.queryByText("No sessions yet")).toBeNull();
  });
});

describe("refresh", () => {
  it("keeps rendering children while a refresh is in flight", () => {
    renderState(success(["Monday"], "loading"));
    expect(screen.getByText("Monday")).toBeDefined();
  });

  it("keeps children AND surfaces a stale signal when a refresh fails", () => {
    renderState(success(["Monday"], "error"));
    expect(screen.getByText("Monday")).toBeDefined();
    expect(screen.getByText("Couldn't refresh — showing your last loaded data.")).toBeDefined();
  });

  it("does not show a stale signal when the refresh is healthy", () => {
    renderState(success(["Monday"]));
    expect(screen.queryByText(/Couldn't refresh/)).toBeNull();
  });

  it("passes the refresh state to children", () => {
    render(
      <ResourceState<Rows>
        resource={success(["Monday"], "loading")}
        guest={{ title: "guest" }}
        empty={{ title: "empty" }}
      >
        {(_rows, refresh) => <span>refresh:{refresh.status}</span>}
      </ResourceState>,
    );
    expect(screen.getByText("refresh:loading")).toBeDefined();
  });
});

describe("screen-supplied slots", () => {
  it("uses a custom loading skeleton without letting the screen reclaim branch selection", () => {
    const skeleton = <div data-testid="skeleton" />;
    renderState({ status: "loading" }, { loading: skeleton });
    expect(screen.getByTestId("skeleton")).toBeDefined();

    cleanup();
    // The same custom skeleton must not appear on any other branch.
    renderState({ status: "error", error: { message: "boom" } }, { loading: skeleton });
    expect(screen.queryByTestId("skeleton")).toBeNull();
    expect(screen.getByRole("alert")).toBeDefined();

    cleanup();
    renderState(success([]), { loading: skeleton });
    expect(screen.queryByTestId("skeleton")).toBeNull();
    expect(screen.getByText("No sessions yet")).toBeDefined();
  });

  it("renders a screen-supplied action", () => {
    const onClick = vi.fn();
    renderState({ status: "guest" }, { guest: { title: "Sign in", action: { label: "Sign in →", onClick } } });
    const button = screen.getByRole("button", { name: "Sign in →" });
    button.click();
    expect(onClick).toHaveBeenCalledOnce();
  });

  it("falls back to the error message as the body when the screen supplies no copy", () => {
    renderState({ status: "error", error: { message: "Timed out" } }, { error: undefined });
    expect(screen.getByText("Timed out")).toBeDefined();
  });
});

describe("accessibility semantics", () => {
  it("announces loading politely", () => {
    renderState({ status: "loading" });
    const node = screen.getByRole("status");
    expect(node.getAttribute("aria-live")).toBe("polite");
  });

  it("announces a no-data error assertively via role=alert", () => {
    renderState({ status: "error", error: { message: "boom" } });
    expect(screen.getByRole("alert")).toBeDefined();
  });

  it("does not announce guest or empty states as live regions", () => {
    renderState({ status: "guest" });
    expect(screen.queryByRole("status")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();

    cleanup();
    renderState(success([]));
    expect(screen.queryByRole("status")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

describe("variants", () => {
  it.each(["screen", "box", "note"] as const)("renders the %s variant on every branch", (variant) => {
    renderState({ status: "guest" }, { variant });
    expect(screen.getByText("Sign in to view your history")).toBeDefined();
    cleanup();
    renderState(success(["Monday"]), { variant });
    expect(screen.getByText("Monday")).toBeDefined();
  });
});
