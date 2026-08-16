// The `prescription` field of `/v1/planning/today` is a GENERATED type, and the
// Overview must keep consuming it as one.
//
// History this locks down: openapi.json declared the field as a bare object, so
// `types.gen.ts` emitted `{ [key: string]: unknown } | null`, which is unusable —
// and AuthedOverview.tsx answered that with a hand-written local shape plus two
// `as` casts. A hand-written duplicate of a contract type cannot fail when the
// contract moves; it just goes quietly wrong. The backend now declares
// `WorkoutPrescription | None`, and these are the two ratchets that keep it that way.
//
// The compile-time half of this guarantee is enforced by `npm run check:types`
// (`tsc --noEmit`, tsconfig.json: strict + noUnusedLocals): the fixture below is
// annotated `TodaySessionResponse`, so it only compiles while `prescription` is
// structurally the generated `WorkoutPrescription`. What is asserted at RUNTIME
// here is the generated artifact and the source, which tsc cannot speak about.
import { describe, expect, it } from "vitest";
import type { TodaySessionResponse, WorkoutPrescription } from "@/types";

const GENERATED_REF = 'components["schemas"]["WorkoutPrescription"]';

/** A fully populated response, typed as the contract. See the header note: the
 *  annotation is the compile-time assertion; tsc rejects this file if the field
 *  ever regresses to an index signature. */
const populated: TodaySessionResponse = {
  session: null,
  prescription: {
    type: "Strength",
    focus: "Heavy Lower",
    rationale: "Readiness is high and the block is in an accumulation week.",
    duration_min: 62,
    model_version: "v0.3",
    exercises: [{ name: "Back Squat", sets: 4, reps: "5", weak_point_tags: [], prescribed_load_kg: 102.5 }],
    why: {
      state_drivers: ["hrv above baseline"],
      goal_alignment: "Strength",
      constraints_applied: ["block:phase=accumulation", "block:rpe_target=8"],
      source_alignment: [],
      warnings: [],
    },
  },
};

describe("TodaySessionResponse.prescription is the generated WorkoutPrescription", () => {
  it("reads model fields through the generated type without a cast", () => {
    // No `as` anywhere in this block — that is the point. Under the old
    // index-signature type every one of these reads was `unknown`.
    const rx: WorkoutPrescription | null | undefined = populated.prescription;
    expect(rx?.focus).toBe("Heavy Lower");
    expect(rx?.duration_min).toBe(62);
    expect(rx?.exercises?.[0]?.name).toBe("Back Squat");
    expect(rx?.why?.constraints_applied).toContain("block:phase=accumulation");
  });

  it("null is still a valid state, so the field stays optional", () => {
    const empty: TodaySessionResponse = { session: null, prescription: null };
    expect(empty.prescription).toBeNull();
  });

  it("types.gen.ts declares the field as a $ref to the model, not an index signature", async () => {
    const { readFileSync } = await import("node:fs");
    const { join } = await import("node:path");
    const src = readFileSync(join(__dirname, "..", "..", "..", "types.gen.ts"), "utf8");

    const block = /TodaySessionResponse:\s*\{([\s\S]*?)\n {8}\};/.exec(src);
    expect(block, "TodaySessionResponse not found in types.gen.ts").not.toBeNull();
    const body = block![1];

    expect(body).toContain(GENERATED_REF);
    // The exact shape openapi-typescript emitted for the old bare-object declaration.
    expect(body).not.toMatch(/\[key: string\]: unknown/);
  });
});

describe("no file re-introduces a hand-rolled prescription shape", () => {
  it("nothing under web/src casts .prescription to a locally declared type", async () => {
    const { readFileSync, readdirSync } = await import("node:fs");
    const { join } = await import("node:path");
    const root = join(__dirname, "..", "..", "..");
    const walk = (dir: string): string[] =>
      readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
        const full = join(dir, e.name);
        // Test files are excluded, matching the ratchet in overviewBehaviour.test.tsx:
        // this file quotes the forbidden pattern in order to forbid it, and must not
        // convict itself.
        return e.isDirectory() ? walk(full) : /\.tsx?$/.test(e.name) && !/\.test\.tsx?$/.test(e.name) ? [full] : [];
      });

    // Both retired offenders wrote the assertion on the same line as the read:
    //   const presc = (data ? data.prescription : null) as PrescriptionShape | null;
    // so "a line mentioning .prescription that also contains `as`" is the exact
    // fingerprint. Verified by running this test against the pre-change revision of
    // AuthedOverview.tsx: it flagged that file, and flags nothing in the current tree.
    const offending = /^.*\.prescription\b.*\bas\b.*$/m;
    const offenders = walk(root).filter((f) => offending.test(readFileSync(f, "utf8")));
    expect(offenders, `cast .prescription away from the generated type in: ${offenders.join(", ")}`).toEqual([]);
  });
});
