// src/perflab/sidebar/sidebarBlockModel.ts
//
// The pure state-product for the sidebar's training-block card.
//
// This exists because the card previously rendered three hardcoded literals —
// "Mid-base", pct={42}, "Week 3 of 7 · build phase" — unconditionally, to every
// viewer. An athlete with zero workouts, zero state rows and zero macrocycles was
// told they were three weeks into a seven-week build phase. Found by in-browser
// verification of B5; the boundary guard could not see it because its root set was
// the Overview screen, and this card lives in the always-visible chrome.
//
// Every value below is API-derived or absent. In particular the progress bar is
// driven by the backend's own `week_progress.pct` (schedule position, already
// 0..100 — app/services/macrocycle_service.py compute_week_progress). The
// frontend does NOT reconstruct a percentage from week numbers: when the horizon
// is open, the backend sends `total_weeks: null` and `pct: null`, and the bar is
// omitted rather than guessed.
import type { AuthedResource } from "../resource";
import { isStale } from "../resource";
import type { MacrocycleRead } from "@/types";

export type SidebarBlockView =
  /** No token: this component has no request authority. Renders nothing. */
  | { kind: "guest" }
  /** Token present, no usable payload yet. A shell — never values, never "empty". */
  | { kind: "loading" }
  /** The request failed with nothing usable on screen. NOT the same as "none". */
  | { kind: "unavailable" }
  /** The request succeeded and the athlete genuinely has no active macrocycle. */
  | { kind: "none" }
  /** A real active macrocycle. `stale` = the last refresh failed; prior data retained. */
  | {
      kind: "block";
      label: string;
      weekLine: string;
      pct: number | null;
      stale: boolean;
    };

/**
 * The active program, chosen deterministically.
 *
 * "Active" is the backend's own `status` enum value, not a frontend judgement.
 * Ties are broken by the most recent `start_date`, then by highest id, so the
 * same list always yields the same card.
 */
function activeMacrocycle(rows: MacrocycleRead[]): MacrocycleRead | null {
  const active = rows.filter((m) => m.status === "active");
  if (active.length === 0) return null;
  return active.slice().sort((a, b) => {
    if (a.start_date !== b.start_date) return a.start_date < b.start_date ? 1 : -1;
    return b.id - a.id;
  })[0];
}

/** "Week 3 of 7" when the horizon is known; "Week 3" when it is open. */
function weekLineFor(m: MacrocycleRead): string {
  const { current_week, total_weeks } = m.week_progress;
  return total_weeks != null ? `Week ${current_week} of ${total_weeks}` : `Week ${current_week}`;
}

export function sidebarBlockView(
  resource: AuthedResource<MacrocycleRead[]>,
): SidebarBlockView {
  switch (resource.status) {
    case "guest":
      return { kind: "guest" };
    case "loading":
      return { kind: "loading" };
    case "error":
      return { kind: "unavailable" };
    case "success": {
      const m = activeMacrocycle(resource.data);
      if (m === null) return { kind: "none" };
      return {
        kind: "block",
        label: m.objective_label,
        weekLine: weekLineFor(m),
        pct: m.week_progress.pct ?? null,
        stale: isStale(resource),
      };
    }
  }
}
