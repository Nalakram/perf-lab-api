// Contract-parity guard for the confidence band.
//
// The backend declares the band once as a Literal and publishes it as an enum;
// `types.gen.ts` is generated from the COMMITTED `openapi.json`, and app code
// consumes the friendly re-export in `types.ts`. Every link in that chain is
// mechanical except one: regeneration is a manual step, so `types.gen.ts` can
// silently fall behind a regenerated contract and `tsc -b` will still exit 0 —
// it type-checks happily against a stale-but-consistent union.
//
// These tests assert the LINKS, not the values, because the values agreeing is
// exactly what a stale file would still look like.
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import type { ConfidenceStatus } from "./types";

const REPO_ROOT = join(__dirname, "..", "..");
const WEB_SRC = join(__dirname);

const EXPECTED = ["established", "provisional", "insufficient"] as const;

/** Exhaustive over the generated union: a value added or removed backend-side
 *  makes this object fail to type-check, which is the compile-time half. */
const LABELS: Record<ConfidenceStatus, string> = {
  established: "Established",
  provisional: "Provisional",
  insufficient: "Insufficient",
};

function contractEnum(): string[] {
  const doc = JSON.parse(readFileSync(join(REPO_ROOT, "openapi.json"), "utf8"));
  const node = doc.components.schemas.StateHistorySnapshotRead.properties.capacity_confidence_status;
  return node.additionalProperties.enum;
}

describe("the confidence band is generated, not hand-declared", () => {
  it("exposes exactly the bands the published contract declares", () => {
    expect(contractEnum()).toEqual([...EXPECTED]);
    expect(Object.keys(LABELS).sort()).toEqual([...EXPECTED].sort());
  });

  it("types.gen.ts carries the enum, so it was regenerated from the current contract", () => {
    // The link that `tsc -b` cannot check: a types.gen.ts generated from an older
    // openapi.json would still compile, and the web would keep consuming `string`.
    const gen = readFileSync(join(WEB_SRC, "types.gen.ts"), "utf8");
    const union = EXPECTED.map((v) => `"${v}"`).join(" | ");
    expect(gen).toContain(union);
    expect(gen).not.toMatch(/confidence_status:\s*string\s*\|\s*null/);
    expect(gen).not.toMatch(/capacity_confidence_status[\s\S]{0,120}\[key: string\]:\s*string;/);
  });

  it("no source file re-declares the band by hand", () => {
    // The defect this candidate existed to remove: the enum written out again in
    // TypeScript, free to drift from the backend without anything failing.
    //
    // Scans the whole tree rather than the one file that had it. Checking only
    // the known offender would let the next copy land unnoticed, which is the
    // failure mode this test exists to prevent.
    const handDeclared = /"established"\s*\|\s*"provisional"\s*\|\s*"insufficient"/;
    const walk = (dir: string): string[] =>
      readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
        const full = join(dir, e.name);
        if (e.isDirectory()) return walk(full);
        return /\.tsx?$/.test(e.name) && e.name !== "types.gen.ts" ? [full] : [];
      });
    const offenders = walk(WEB_SRC)
      .filter((f) => f !== __filename)
      .filter((f) => handDeclared.test(readFileSync(f, "utf8")))
      .map((f) => f.slice(WEB_SRC.length + 1));
    expect(offenders).toEqual([]);

    const capacityView = readFileSync(
      join(WEB_SRC, "perflab", "screens", "twin", "CapacityView.tsx"),
      "utf8",
    );
    expect(capacityView).toContain("ConfidenceStatus");
  });
});
