// Pure data helpers for HistoryScreen — no React / API imports, so they are
// unit-testable through their interface (the screen composes them into cards).
// The state-vector reductions (readiness/fatigue/aerobic) live in the shared
// ../stateVector module; only the History-specific window + weekly-load math is here.
import type { StateHistorySnapshotRead, WorkoutLogSummary } from "@/types";

export const RANGES = ["4w", "12w", "All"] as const;
export type Range = (typeof RANGES)[number];
export const RANGE_WEEKS: Record<Range, number> = { "4w": 4, "12w": 12, All: 52 };

/** History's aerobic-capacity track ceiling (0–650 axis). Local display choice —
 *  deliberately not unified with the projection screen's soft display maxima. */
export const AEROBIC_CEILING = 650;

/** Snapshots within the last `weeks` weeks (module-level so the `Date.now()`
 *  clock read stays out of the component render body). */
export function filterHistoryWindow(rows: StateHistorySnapshotRead[], weeks: number): StateHistorySnapshotRead[] {
  const now = Date.now();
  const windowMs = weeks * 7 * 864e5;
  return rows.filter((r) => now - new Date(r.timestamp).getTime() <= windowMs);
}

/** Aggregate logged workouts into the last `weeks` Mon-anchored weekly load totals
 *  (oldest→newest). Returns null when there's nothing to show. */
export function weeklyLoad(workouts: WorkoutLogSummary[] | null, weeks: number): number[] | null {
  if (!workouts || workouts.length === 0) return null;
  const msWeek = 7 * 864e5;
  const now = Date.now();
  const buckets = new Array(weeks).fill(0);
  let any = false;
  for (const w of workouts) {
    const t = new Date(w.session_timestamp ?? w.logged_at).getTime();
    if (Number.isNaN(t)) continue;
    const idx = weeks - 1 - Math.floor((now - t) / msWeek);
    if (idx >= 0 && idx < weeks) { buckets[idx] += w.total_volume_load ?? 0; any = true; }
  }
  return any ? buckets : null;
}
