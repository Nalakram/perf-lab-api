import { describe, expect, it } from "vitest";
import type { ObjectiveRead } from "@/types";
import type { AuthedResource } from "../resource";
import { goalChipsView } from "./goalChipsView";

const objective = (id: number, domain: string): ObjectiveRead =>
  ({ id, domain, status: "active", label: `obj-${id}` }) as ObjectiveRead;

const RUN = objective(1, "run");
const LIFT = objective(2, "lift");

type Res = AuthedResource<ObjectiveRead[]>;
type Refresh = Extract<Res, { status: "success" }>["refresh"];
const success = (data: ObjectiveRead[], refresh: Refresh = { status: "idle" }): Res => ({
  status: "success",
  data,
  refresh,
});

describe("guest", () => {
  it("hides the grid and asks for sign-in rather than showing unlit chips", () => {
    const view = goalChipsView({ status: "guest" });
    expect(view.showGrid).toBe(false);
    expect(view.interactive).toBe(false);
    expect(view.note).toBe("Sign in to train for more than one goal.");
  });
});

describe("first load", () => {
  it("shows unlit chips but refuses interaction until the set is known", () => {
    const view = goalChipsView({ status: "loading" });
    expect(view.objectives).toEqual([]);
    expect(view.interactive).toBe(false);
    expect(view.note).toBe("Loading your goals…");
  });
});

describe("failure with no usable set", () => {
  it("says the load failed instead of presenting an empty set as the truth", () => {
    const view = goalChipsView({ status: "error", error: { message: "Network down" } });
    expect(view.objectives).toEqual([]);
    expect(view.note).toContain("Couldn't load your goals");
    expect(view.note).toContain("Network down");
    expect(view.noteTone).toBe("hot");
    // Chips render unlit, but toggling would compute a priority from an unknown
    // set — so the grid must be inert, not merely unlit.
    expect(view.interactive).toBe(false);
  });
});

describe("success", () => {
  it("lights chips from the loaded objectives", () => {
    const view = goalChipsView(success([RUN, LIFT]));
    expect(view.objectives).toEqual([RUN, LIFT]);
    expect(view.interactive).toBe(true);
    expect(view.note).toBeNull();
  });

  it("keeps the previous chips lit through a toggle-triggered refetch", () => {
    // The regression this pilot exists to prevent: every chip flashing off
    // after a single toggle, because the refetch dropped the payload.
    const view = goalChipsView(success([RUN, LIFT], { status: "loading" }));
    expect(view.objectives).toEqual([RUN, LIFT]);
    expect(view.interactive).toBe(true);
    expect(view.note).toBeNull();
  });

  it("keeps the chips lit when the refresh FAILS, but says the set is stale", () => {
    const view = goalChipsView(success([RUN, LIFT], { status: "error", error: { message: "Timed out" } }));
    expect(view.objectives).toEqual([RUN, LIFT]);
    expect(view.note).toBe("Couldn't refresh your goals — these chips show your last loaded set.");
    expect(view.noteTone).toBe("hot");
    // Still usable: the last loaded set is real data, not a guess.
    expect(view.interactive).toBe(true);
  });

  it("distinguishes a genuinely empty set from a failure", () => {
    const empty = goalChipsView(success([]));
    const failed = goalChipsView({ status: "error", error: { message: "boom" } });
    expect(empty.objectives).toEqual([]);
    expect(empty.note).toBeNull();
    expect(empty.interactive).toBe(true);
    expect(failed.note).not.toBeNull();
    expect(failed.interactive).toBe(false);
  });
});
