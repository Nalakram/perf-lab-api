import { describe, expect, it } from "vitest";
import { axisLabel, BAND, BAND_RANK, narrowStatus } from "./axes";

describe("axisLabel", () => {
  it("names the fatigue axes a session actually drives", () => {
    expect(axisLabel("fatigue_f.cns")).toBe("CNS fatigue");
    expect(axisLabel("fatigue_f.grip")).toBe("Grip fatigue");
  });

  it("names the capacity axes a measurement would sharpen", () => {
    expect(axisLabel("max_strength")).toBe("Max strength");
    expect(axisLabel("work_capacity")).toBe("Work capacity");
  });

  it("names the families the engine models no uncertainty for", () => {
    expect(axisLabel("tissue_t")).toBe("Tissue");
    expect(axisLabel("skill_state")).toBe("Skill");
  });

  // An axis added backend-side must degrade to a rough label, never vanish from a list
  // the athlete is reading to understand their plan.
  it("humanises an axis it has never heard of rather than dropping it", () => {
    expect(axisLabel("fatigue_f.thoracic")).toBe("Thoracic");
    expect(axisLabel("some_new_axis")).toBe("Some new axis");
  });

  it("never returns an empty string for a non-empty axis", () => {
    for (const axis of ["a", "x_y", "fatigue_f.z", "UNKNOWN"]) {
      expect(axisLabel(axis).length).toBeGreaterThan(0);
    }
  });
});

describe("narrowStatus", () => {
  it("passes through the three bands the contract declares", () => {
    expect(narrowStatus("established")).toBe("established");
    expect(narrowStatus("provisional")).toBe("provisional");
    expect(narrowStatus("insufficient")).toBe("insufficient");
  });

  // Version skew: a running SPA can receive a band this build has never heard of.
  // Rendering it as understood — worse, as non-insufficient, which would admit it to
  // every "is this measured?" branch — claims more than we know.
  it("degrades an unknown or absent band to the conservative default", () => {
    expect(narrowStatus("wildly_confident")).toBe("insufficient");
    expect(narrowStatus(undefined)).toBe("insufficient");
    expect(narrowStatus(null)).toBe("insufficient");
    expect(narrowStatus("")).toBe("insufficient");
  });

  it("does not treat inherited Object properties as bands", () => {
    expect(narrowStatus("toString")).toBe("insufficient");
    expect(narrowStatus("constructor")).toBe("insufficient");
  });
});

describe("BAND", () => {
  it("words every band as evidence the athlete can act on", () => {
    expect(BAND.established.label).toBe("measured");
    expect(BAND.insufficient.label).toBe("unmeasured");
  });

  it("gives each band a distinct colour treatment", () => {
    const classes = [BAND.established.cls, BAND.provisional.cls, BAND.insufficient.cls];
    expect(new Set(classes).size).toBe(3);
  });

  it("ranks least-certain first, so the axis that should constrain trust leads", () => {
    expect(BAND_RANK.insufficient).toBeLessThan(BAND_RANK.provisional);
    expect(BAND_RANK.provisional).toBeLessThan(BAND_RANK.established);
  });
});
