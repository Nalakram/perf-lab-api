// src/perflab/overlays/workoutLogBoundary.test.ts
//
// THE STATIC HALF OF THE WORKOUT-LOG HONESTY ORACLE (#199).
//
// Claim under test: starting from the module that builds the authenticated
// `POST /v1/log-workout` request body, and following every value-carrying import edge
// transitively, no fixture module is reachable. A seeded sample constant cannot enter
// an authenticated submission because there is no path along which it could travel.
//
// This is the structural half of "make it impossible", and it is not sufficient alone:
// a fabricated value can still be handed IN as a parameter or read from the store. That
// property is tested by workoutLogBody.test.ts, which sweeps the state product. Neither
// test substitutes for the other, which is why both are required.
//
// WHY THE ROOT IS workoutLogBody.ts AND NOT LogWorkoutModal.tsx. The modal renders the
// dose-preview chrome and legitimately value-imports the fixture module `../sim`
// (COLORS, DOSE_NAMES, doseBarColor, PRESETS, projectLogDose — LogWorkoutModal.tsx:9),
// so a walk rooted at the modal would be red for a reason that has nothing to do with
// what gets submitted, and the only way to "fix" it would be to gut the preview. The
// body builder was extracted into its own fixture-free module precisely so this guard
// has a root that is both meaningful and achievable. That the modal cannot reach a
// fixture VALUE into the body is the job of the behavioural suite, plus the assertion
// below that the modal reads no check-in field directly.
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { findForbidden, p, resolveLocal, valueImportsOf } from "@/testing/importGraph";

// The authenticated submit path's body builder. Everything that ends up in the JSON
// sent to /v1/log-workout is decided here.
const SUBMIT_ROOTS = [
  p("perflab", "overlays", "workoutLogBody.ts"),
  // The wellness sibling: POST /v1/wellness is the other place a check-in value is
  // sent to the backend under the athlete's own authority.
  p("perflab", "wellnessSignals.ts"),
];

// Canonical resolved paths of every module that exists to hold sample/fixture data.
const FIXTURE_MODULES = new Set([
  p("perflab", "sim.ts"),
  p("perflab", "screens", "overview", "GuestOverviewPreview.tsx"),
  p("perflab", "screens", "twin", "GuestTwinPreview.tsx"),
]);

describe("the authenticated workout-log submit cannot reach fixture data (#199)", () => {
  it("resolves the alias table from the real tsconfig", () => {
    // If alias resolution silently broke, every `@/...` edge would resolve to null and
    // the guard would pass by seeing almost no graph at all.
    expect(resolveLocal("@/types", SUBMIT_ROOTS[0])).toBe(p("types.ts"));
  });

  it("POSITIVE CONTROL: the walker does find a fixture module that IS reachable", () => {
    // LogWorkoutModal.tsx imports sim.ts directly and legitimately, for preview chrome.
    // If this stops failing, the walker has stopped walking and the real assertion
    // below is passing vacuously.
    const hit = findForbidden(
      [p("perflab", "overlays", "LogWorkoutModal.tsx")],
      new Set([p("perflab", "sim.ts")]),
    );
    expect(hit.reached).toBe(true);
    expect(hit.chain[hit.chain.length - 1]).toBe("perflab/sim.ts");
  });

  it("POSITIVE CONTROL: a forbidden set the root genuinely imports is detected", () => {
    // Guards against the walker returning `false` for a root whose edges it failed to
    // parse at all — setBuilderLogic IS a real value import of workoutLogBody.ts.
    const hit = findForbidden(
      [p("perflab", "overlays", "workoutLogBody.ts")],
      new Set([p("perflab", "overlays", "setBuilderLogic.ts")]),
    );
    expect(hit.reached).toBe(true);
  });

  it("reaches no fixture module from the request-body builder", () => {
    const hit = findForbidden(SUBMIT_ROOTS, FIXTURE_MODULES);
    const detail = hit.reached
      ? `\n\nFixture module reachable from the authenticated workout-log submit.\nImport chain:\n  ${hit.chain.join("\n    -> ")}\n`
      : "";
    expect(hit.reached, detail).toBe(false);
  });

  it("the body builder's only edge to the fixture module is type-only", () => {
    // `import type { CheckinState } from "../sim"` is erased at build time. Asserting
    // it explicitly stops a future edit from turning it into a value import and
    // quietly re-opening the channel — the walker would catch it, but this names it.
    const body = p("perflab", "overlays", "workoutLogBody.ts");
    const specifiers = valueImportsOf(body);
    expect(specifiers).not.toContain("../sim");
    expect(readFileSync(body, "utf8")).toContain('import type { CheckinState } from "../sim"');
  });

  it("LogWorkoutModal reads no raw check-in field on the submit path", () => {
    // The defect was `const { sleepQ, mood } = state.checkin` feeding the body
    // directly. The modal may consult the check-in ONLY through the null-preserving
    // mapper, so the seeded-constant channel cannot be reopened by a one-line edit.
    const src = readFileSync(p("perflab", "overlays", "LogWorkoutModal.tsx"), "utf8");
    expect(src).toContain("checkinToWorkoutWellness(state.checkin)");
    for (const field of ["sleepQ", "mood", "sleepH", "hrv", "rhr", "soreness", "stress"]) {
      expect(src, `LogWorkoutModal must not read state.checkin.${field} directly`).not.toMatch(
        new RegExp(`checkin\\.${field}\\b|\\b${field}\\s*[,}]\\s*=\\s*state\\.checkin`),
      );
    }
  });
});
