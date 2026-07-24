import { describe, expect, it } from "vitest";
import type { StateHistorySnapshotRead, WorkoutLogSummary } from "@/types";
import { aerobicValue, filterHistoryWindow, stateReadinessProxy, weeklyLoad } from "./historyData";

// Only the fields under test matter; cast minimal rows.
const snap = (daysAgo: number, extra: Partial<StateHistorySnapshotRead> = {}): StateHistorySnapshotRead =>
  ({ timestamp: new Date(Date.now() - daysAgo * 864e5).toISOString(), ...extra } as StateHistorySnapshotRead);
const workout = (daysAgo: number, load: number): WorkoutLogSummary =>
  ({ session_timestamp: new Date(Date.now() - daysAgo * 864e5).toISOString(), total_volume_load: load } as WorkoutLogSummary);

describe("filterHistoryWindow", () => {
  it("keeps only snapshots within the last N weeks", () => {
    const rows = [snap(2), snap(20), snap(40), snap(200)];
    expect(filterHistoryWindow(rows, 4)).toHaveLength(2); // 28d window
    expect(filterHistoryWindow(rows, 12)).toHaveLength(3); // 84d window
    expect(filterHistoryWindow(rows, 52)).toHaveLength(4); // 364d window
  });

  it("returns an empty array when nothing falls in the window", () => {
    expect(filterHistoryWindow([snap(100), snap(300)], 4)).toEqual([]);
  });

  it("preserves the order of the rows it keeps", () => {
    const rows = [snap(1), snap(5), snap(3)];
    expect(filterHistoryWindow(rows, 4).map((r) => r.timestamp)).toEqual(rows.map((r) => r.timestamp));
  });
});

describe("weeklyLoad", () => {
  it("returns null for empty or absent input (empty state, never a mock)", () => {
    expect(weeklyLoad(null, 12)).toBeNull();
    expect(weeklyLoad([], 12)).toBeNull();
  });

  it("buckets real load into the last N weeks, newest in the final bucket", () => {
    const buckets = weeklyLoad([workout(1, 100), workout(8, 50)], 4);
    expect(buckets).not.toBeNull();
    expect(buckets!).toHaveLength(4);
    expect(buckets![3]).toBe(100); // this week
    expect(buckets![2]).toBe(50); // last week
    expect(buckets![0]).toBe(0);
  });

  it("returns null when every workout is older than the window", () => {
    expect(weeklyLoad([workout(60, 100)], 4)).toBeNull();
  });
});

describe("aerobicValue", () => {
  it("prefers the decomposed axis, falling back to the legacy scalar", () => {
    expect(aerobicValue(snap(0, { capacity_x: { aerobic: 420 } as StateHistorySnapshotRead["capacity_x"], c_met_aerobic: 999 }))).toBe(420);
    expect(aerobicValue(snap(0, { c_met_aerobic: 310 }))).toBe(310);
  });
});

describe("stateReadinessProxy", () => {
  it("is 100 at zero fatigue and drops as fatigue rises", () => {
    const zero = { fatigue_f: { cns: 0, muscular: 0, metabolic: 0, structural: 0, tendon: 0, grip: 0 } } as unknown as Parameters<typeof stateReadinessProxy>[0];
    const tired = { fatigue_f: { cns: 60, muscular: 60, metabolic: 60, structural: 60, tendon: 60, grip: 60 } } as unknown as Parameters<typeof stateReadinessProxy>[0];
    expect(stateReadinessProxy(zero)).toBe(100);
    expect(stateReadinessProxy(tired)).toBe(40);
  });
});
