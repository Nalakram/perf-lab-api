import { describe, expect, it } from "vitest";
import type { StateHistorySnapshotRead, WorkoutLogSummary } from "@/types";
import { filterHistoryWindow, weeklyLoad } from "./historyData";

const snap = (daysAgo: number): StateHistorySnapshotRead =>
  ({ timestamp: new Date(Date.now() - daysAgo * 864e5).toISOString() } as StateHistorySnapshotRead);
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
