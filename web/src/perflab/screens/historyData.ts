// Pure data helpers for HistoryScreen — no React / API imports, so they are
// unit-testable through their interface (the screen composes them into cards).
import type { StateHistorySnapshotRead, UnifiedStateVector, WorkoutLogSummary } from "@/types";

export const RANGES = ["4w", "12w", "All"] as const;
export type Range = (typeof RANGES)[number];
export const RANGE_WEEKS: Record<Range, number> = { "4w": 4, "12w": 12, All: 52 };

/** The twin's aerobic capacity ceiling (0–650 axis), used to fill the track. */
export const AEROBIC_CEILING = 650;

/** Readiness proxy ~ (1 − mean fatigue), scaled 0–100 — mirrors the backend
 *  `overall_readiness` intent for the trend line (same as Overview). */
export function stateReadinessProxy(sv: UnifiedStateVector): number {
  const f = sv.fatigue_f;
  const vals = f
    ? [f.cns, f.muscular, f.metabolic, f.structural, f.tendon, f.grip]
    : [sv.f_nm_central, sv.f_nm_peripheral, sv.f_met_systemic, sv.f_struct_damage];
  const mean = vals.reduce((a, b) => a + b, 0) / vals.length;
  return Math.round(Math.max(0, Math.min(100, 100 - mean)));
}

/** Aerobic-capacity value for a snapshot: the decomposed axis when present,
 *  else the legacy scalar mirror. */
export function aerobicValue(sv: StateHistorySnapshotRead): number {
  return sv.capacity_x?.aerobic ?? sv.c_met_aerobic;
}

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
