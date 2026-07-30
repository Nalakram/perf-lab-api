// src/perflab/screens/overview/overviewBoundary.test.ts
//
// THE STATIC HALF OF THE OVERVIEW HONESTY ORACLE (map #182, #189b).
//
// Claim under test: starting from the authenticated Overview roots and following
// every value-carrying import edge transitively, no fixture module is reachable.
//
// Why this and not the alternatives, both of which were ruled out in #189:
//   - ESLint cannot enforce it. `.github/workflows/ci.yml:207-209` runs lint with
//     `continue-on-error: true`, and lint already exits 1 on three pre-existing
//     errors, so an ESLint rule would be a suggestion, not a gate.
//   - The B3 migration ratchet cannot enforce it. It matches `/\.data\s*\?\?/`,
//     which does not match Overview's actual fixture fallbacks (`.data?.score ??
//     null`), so migrating the file would have turned every check green while all
//     five leaks survived.
//
// Resolution is done by the TypeScript compiler API against the real tsconfig, so
// path aliases (`@/*`), extensionless specifiers, `.ts`/`.tsx` selection, index
// barrels, re-exports, dynamic `import()`, and `import =`/`require` all resolve the
// way the build resolves them. The forbidden set is a set of CANONICAL RESOLVED
// PATHS — never a filename pattern like `*sim*`, which would both miss a renamed
// fixture module and falsely accuse an innocent file named `similarity.ts`.
//
// TYPE-ONLY EDGES ARE NOT EDGES. `import type { CheckinState } from "./sim"` is
// erased at build time and carries no fixture data. Counting it would make the
// guard permanently red for a reason that has nothing to do with honesty.
// The walker itself now lives in src/testing/importGraph.ts so the #199 workout-log
// guard uses the IDENTICAL mechanism rather than a drifting copy. This file keeps its
// own positive control below, which is what makes the sharing safe: a walker that
// stopped walking fails each guard independently instead of silently passing both.
import { describe, expect, it } from "vitest";
import { findForbidden, p, resolveLocal } from "@/testing/importGraph";

// Every authenticated authority-bearing surface, not just the Overview screen.
//
// The Overview-only root set is exactly why the sidebar's block card shipped
// three hardcoded literals ("Mid-base", 42%, "Week 3 of 7 · build phase") to
// signed-in athletes with no macrocycle at all: the card is always-visible
// chrome, so the walk starting at AuthedOverview.tsx could never reach it.
// A surface belongs here if an authenticated athlete can see it and it can
// assert anything about their own data.
const AUTHED_ROOTS = [
  // Overview screen
  p("perflab", "screens", "overview", "AuthedOverview.tsx"),
  p("perflab", "screens", "overview", "overviewModel.ts"),
  p("perflab", "screens", "overview", "overviewLeaves.tsx"),
  // Always-visible chrome
  p("perflab", "sidebar", "AuthedSidebarBlock.tsx"),
  p("perflab", "sidebar", "sidebarBlockModel.ts"),
];

// DELIBERATELY NOT A ROOT: overlays/SessionPlayer.tsx.
//
// It imports PHASES from sim.ts (SessionPlayer.tsx:5) and that import is
// legitimate, because the player is a GUEST-ONLY surface: SessionPlayer.tsx:28
// is `if (token != null) return null`, so an authenticated athlete never sees
// it. Listing it here would fail this guard for a component that bears no
// authenticated authority, and the only way to "fix" that failure would be to
// break the guest preview. Its authenticated behaviour is proved by the
// rejection test over that boundary, not by import reachability.

const FIXTURE_MODULES = new Set([
  p("perflab", "sim.ts"),
  p("perflab", "screens", "overview", "GuestOverviewPreview.tsx"),
  p("perflab", "screens", "twin", "GuestTwinPreview.tsx"),
]);

describe("authenticated Overview cannot reach fixture data", () => {
  it("resolves the alias table from the real tsconfig", () => {
    // If alias resolution silently broke, every `@/...` edge would resolve to null
    // and the guard would pass by seeing almost no graph at all.
    const resolved = resolveLocal("@/types", AUTHED_ROOTS[0]);
    expect(resolved).toBe(p("types.ts"));
  });

  it("POSITIVE CONTROL: the walker does find a fixture module that IS reachable", () => {
    // The guest preview imports sim.ts directly and legitimately. If this stops
    // failing, the walker has stopped walking and the real assertion below is
    // passing vacuously.
    const guest = [p("perflab", "screens", "overview", "GuestOverviewPreview.tsx")];
    const hit = findForbidden(guest, new Set([p("perflab", "sim.ts")]));
    expect(hit.reached).toBe(true);
    expect(hit.chain[hit.chain.length - 1]).toBe("perflab/sim.ts");
  });

  it("reaches no fixture module from any authenticated Overview root", () => {
    const hit = findForbidden(AUTHED_ROOTS, FIXTURE_MODULES);
    const detail = hit.reached
      ? `\n\nForbidden module reachable from authenticated Overview.\nImport chain:\n  ${hit.chain.join("\n    -> ")}\n`
      : "";
    expect(hit.reached, detail).toBe(false);
  });
});
