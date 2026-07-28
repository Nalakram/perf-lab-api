// src/perflab/sidebar/sidebarBlockModel.test.ts
//
// Behavioural oracle for the sidebar block card.
//
// The defect this locks out: the card rendered "Mid-base", a 42% bar and
// "Week 3 of 7 · build phase" unconditionally, so an athlete with no macrocycle
// at all was told they were mid-programme. Type-checking, lint and the existing
// vitest suite all passed while that was true — it took opening a browser.
import { describe, expect, it } from "vitest";

import type { AuthedResource } from "../resource";
import type { MacrocycleRead } from "@/types";
import { sidebarBlockView } from "./sidebarBlockModel";

/** The three literals that must never appear unless real data produced them. */
const FABRICATIONS = ["Mid-base", "Week 3 of 7", "build phase"];

function macrocycle(over: Partial<MacrocycleRead> = {}): MacrocycleRead {
  return {
    id: 1,
    user_id: 1,
    objective_id: 1,
    start_date: "2026-06-01",
    status: "active",
    created_at: "2026-06-01T00:00:00Z",
    updated_at: "2026-06-01T00:00:00Z",
    objective_label: "Sub-20 5k",
    target_date: "2026-08-01",
    block_count: 3,
    week_progress: { current_week: 4, total_weeks: 9, pct: 44.4, weeks_to_go: 5 },
    ...over,
  } as MacrocycleRead;
}

const ok = (rows: MacrocycleRead[]): AuthedResource<MacrocycleRead[]> => ({
  status: "success",
  data: rows,
  refresh: { status: "idle" },
});

const refreshFailed = (rows: MacrocycleRead[]): AuthedResource<MacrocycleRead[]> => ({
  status: "success",
  data: rows,
  refresh: { status: "error", error: { message: "boom" } },
});

describe("sidebarBlockView", () => {
  it("authed + empty macrocycle list -> 'No active block', never a literal", () => {
    const view = sidebarBlockView(ok([]));
    expect(view).toEqual({ kind: "none" });
  });

  it("authed + only non-active macrocycles -> 'No active block'", () => {
    const view = sidebarBlockView(ok([macrocycle({ status: "achieved" })]));
    expect(view.kind).toBe("none");
  });

  it("authed + real active macrocycle -> exact API-derived values", () => {
    const view = sidebarBlockView(ok([macrocycle()]));
    expect(view).toEqual({
      kind: "block",
      label: "Sub-20 5k",
      weekLine: "Week 4 of 9",
      pct: 44.4,
      stale: false,
    });
  });

  it("omits the bar when the backend reports an open horizon (pct null)", () => {
    // compute_week_progress sends total_weeks/pct as null when there is no
    // target date. The frontend must NOT reconstruct a percentage from weeks.
    const open = macrocycle({
      target_date: null,
      week_progress: { current_week: 4, total_weeks: null, pct: null, weeks_to_go: null },
    });
    const view = sidebarBlockView(ok([open]));
    expect(view).toMatchObject({ kind: "block", weekLine: "Week 4", pct: null });
  });

  it("authed + error -> unavailable; not empty and not sample", () => {
    const view = sidebarBlockView({ status: "error", error: { message: "nope" } });
    expect(view).toEqual({ kind: "unavailable" });
    expect(view.kind).not.toBe("none");
  });

  it("initial loading -> loading; never an empty state (no flash)", () => {
    expect(sidebarBlockView({ status: "loading" })).toEqual({ kind: "loading" });
  });

  it("refresh error -> prior real block retained, marked stale", () => {
    const view = sidebarBlockView(refreshFailed([macrocycle()]));
    expect(view).toMatchObject({ kind: "block", label: "Sub-20 5k", stale: true });
  });

  it("guest -> guest (the authed card renders nothing; the sample card is separate)", () => {
    expect(sidebarBlockView({ status: "guest" })).toEqual({ kind: "guest" });
  });

  it("picks the most recently started active programme, deterministically", () => {
    const older = macrocycle({ id: 1, start_date: "2026-01-01", objective_label: "Old" });
    const newer = macrocycle({ id: 2, start_date: "2026-06-01", objective_label: "New" });
    expect(sidebarBlockView(ok([older, newer]))).toMatchObject({ label: "New" });
    expect(sidebarBlockView(ok([newer, older]))).toMatchObject({ label: "New" });
  });

  it("NO authenticated branch can produce Mid-base / 42% / Week 3 of 7", () => {
    const branches: AuthedResource<MacrocycleRead[]>[] = [
      { status: "loading" },
      { status: "error", error: { message: "x" } },
      ok([]),
      ok([macrocycle()]),
      refreshFailed([macrocycle()]),
      ok([macrocycle({ status: "abandoned" })]),
    ];
    for (const branch of branches) {
      const rendered = JSON.stringify(sidebarBlockView(branch));
      for (const lie of FABRICATIONS) {
        expect(rendered, `"${lie}" leaked from ${branch.status}`).not.toContain(lie);
      }
      expect(rendered).not.toContain("42");
    }
  });
});
