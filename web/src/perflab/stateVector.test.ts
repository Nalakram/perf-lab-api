import { describe, expect, it } from "vitest";
import type { CapacityState, StateHistorySnapshotRead, UnifiedStateVector } from "@/types";
import {
  aerobicValue,
  fatigueDisplayProxy,
  meanFatigue,
  peakTissue,
  readCapacity,
  snapshotCapacity,
} from "./stateVector";

const sv = (extra: Partial<UnifiedStateVector>): UnifiedStateVector => extra as UnifiedStateVector;
const fatigue = (v: number) => ({ cns: v, muscular: v, metabolic: v, structural: v, tendon: v, grip: v });

describe("meanFatigue", () => {
  it("averages the six decomposed axes when present", () => {
    expect(meanFatigue(sv({ fatigue_f: fatigue(30) as UnifiedStateVector["fatigue_f"] }))).toBe(30);
  });
  it("falls back to the legacy scalars when the decomposed vector is absent", () => {
    // golden parity: same reduction as the pre-extraction copies used.
    expect(meanFatigue(sv({ f_nm_central: 20, f_nm_peripheral: 40, f_met_systemic: 20, f_struct_damage: 40 }))).toBe(30);
  });
});

describe("fatigueDisplayProxy (non-canonical, display only)", () => {
  it("is 100 at zero fatigue and drops as fatigue rises", () => {
    expect(fatigueDisplayProxy(sv({ fatigue_f: fatigue(0) as UnifiedStateVector["fatigue_f"] }))).toBe(100);
    expect(fatigueDisplayProxy(sv({ fatigue_f: fatigue(60) as UnifiedStateVector["fatigue_f"] }))).toBe(40);
  });
});

describe("peakTissue", () => {
  it("returns the highest-loaded region, capitalized", () => {
    expect(peakTissue(sv({ tissue_t: { ankle: 10, knee: 55, elbow: 20 } as UnifiedStateVector["tissue_t"] }))).toEqual({ region: "Knee", value: 55 });
  });
  it("returns null with no tissue vector", () => {
    expect(peakTissue(sv({}))).toBeNull();
  });
});

describe("readCapacity — runtime-honest, missing never becomes 0", () => {
  const cap = (o: Partial<CapacityState>) => o as CapacityState;
  it("returns the value when present and finite", () => {
    expect(readCapacity(cap({ aerobic: 400 }), "aerobic")).toEqual({ availability: "available", value: 400 });
  });
  it("marks a missing state unavailable, not 0", () => {
    expect(readCapacity(null, "aerobic")).toEqual({ availability: "unavailable", reason: "missing_axis" });
    expect(readCapacity(undefined, "power")).toEqual({ availability: "unavailable", reason: "missing_axis" });
  });
  it("marks a missing axis unavailable, not 0", () => {
    expect(readCapacity(cap({}), "power")).toEqual({ availability: "unavailable", reason: "missing_axis" });
  });
  it("rejects non-finite values (malformed payload / stale types)", () => {
    expect(readCapacity(cap({ aerobic: NaN }), "aerobic")).toEqual({ availability: "unavailable", reason: "non_finite_value" });
    expect(readCapacity(cap({ aerobic: Infinity }), "aerobic")).toEqual({ availability: "unavailable", reason: "non_finite_value" });
  });
  it("rejects an invalid capacity key at compile time", () => {
    // @ts-expect-error 'not_an_axis' is not a keyof CapacityState
    readCapacity(cap({ aerobic: 1 }), "not_an_axis");
  });
});

describe("snapshotCapacity — decomposed axis, else legacy mirror, else null", () => {
  const snap = (o: Partial<StateHistorySnapshotRead>) => o as StateHistorySnapshotRead;
  it("prefers the decomposed axis", () => {
    expect(snapshotCapacity(snap({ capacity_x: { aerobic: 420 } as StateHistorySnapshotRead["capacity_x"], c_met_aerobic: 999 }), "aerobic")).toBe(420);
  });
  it("falls back to the legacy mirror when the axis is missing", () => {
    expect(snapshotCapacity(snap({ c_met_aerobic: 310 }), "aerobic")).toBe(310);
    expect(snapshotCapacity(snap({ c_nm_force: 150 }), "max_strength")).toBe(150);
  });
  it("returns null (never 0) for an axis with no value and no mirror", () => {
    expect(snapshotCapacity(snap({}), "power")).toBeNull();
  });
});

describe("aerobicValue", () => {
  it("prefers the decomposed axis, falling back to the legacy scalar", () => {
    expect(aerobicValue({ capacity_x: { aerobic: 420 } as StateHistorySnapshotRead["capacity_x"], c_met_aerobic: 999 } as StateHistorySnapshotRead)).toBe(420);
    expect(aerobicValue({ c_met_aerobic: 310 } as StateHistorySnapshotRead)).toBe(310);
  });
});

// Readiness-authority guard: the shared module must not export anything named
// like the canonical readiness number (that stays backend-owned via getReadiness).
describe("readiness authority", () => {
  it("exports no ambiguous 'readiness' helper", async () => {
    const mod = await import("./stateVector");
    for (const name of Object.keys(mod)) expect(name.toLowerCase()).not.toContain("readiness");
  });
});
