// src/perflab/prescription/axes.ts
//
// Shared vocabulary for rendering the prescription explanation contract
// (`WorkoutPrescription.why`) across Planning, Twin and Assess.
//
// Two jobs, both presentation-only:
//   • turning a backend state-axis identifier into words an athlete reads, and
//   • narrowing the confidence band the backend published into something safe to render.
//
// It computes no measurement and interprets no physiology — the labels are names for
// fields the engine already decided about.

import type { ConfidenceStatus } from "@/types";

// ---- Axis labels ---------------------------------------------------------------
//
// Only the axes that arrive WITHOUT a label of their own need an entry here.
// `StateEvidence` and `PlanRevisionTrigger` each carry the driver rule's own `label`
// (app/logic/prescription_finalize.py `_DRIVER_RULES`), so those render the backend's
// phrase and never consult this map — the phrase and the number behind it come from
// one row on purpose, and re-deriving the phrase here would be exactly the drift that
// pairing them was meant to prevent.
//
// What DOES need labels:
//   • `expected_outcomes.axis` — the six fatigue fields the forward model drives.
//   • `measurement_recommendations.axis` — the five capacity axes.
//   • `confidence.uncertainty_not_modelled` — state FAMILIES, not single axes.
//
// The five capacity labels are deliberately the same words CapacityView shows for the
// same fields; that component keeps its own table because it also carries drawing
// ceilings, which are a chart concern rather than a naming one.
const AXIS_LABELS: Record<string, string> = {
  // Fatigue axes driven by a session (ExpectedOutcome).
  "fatigue_f.cns": "CNS fatigue",
  "fatigue_f.muscular": "Muscular fatigue",
  "fatigue_f.metabolic": "Metabolic fatigue",
  "fatigue_f.structural": "Structural fatigue",
  "fatigue_f.tendon": "Tendon fatigue",
  "fatigue_f.grip": "Grip fatigue",
  // Capacity axes (MeasurementRecommendation).
  aerobic: "Aerobic",
  glycolytic: "Glycolytic",
  max_strength: "Max strength",
  power: "Power",
  work_capacity: "Work capacity",
  // Families the engine keeps no variance for (PrescriptionConfidence).
  fatigue_f: "Fatigue",
  tissue_t: "Tissue",
  skill_state: "Skill",
};

/**
 * An axis identifier as words. Unknown axes are humanised rather than dropped: a field
 * added backend-side should read as a slightly rough label, never vanish from a list the
 * athlete is using to understand their plan.
 */
export function axisLabel(axis: string): string {
  const known = AXIS_LABELS[axis];
  if (known != null) return known;
  const words = axis.replace(/^[a-z]+_[a-z]\./, "").replace(/[._]/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

// ---- Confidence bands ----------------------------------------------------------
//
// The narrowing mirrors CapacityView's: the generated union governs this build, not the
// wire. Under SPA/backend version skew a response can carry a band this build has never
// heard of, and rendering it as understood — worse, as non-insufficient — is a stronger
// claim than degrading to the conservative default. KNOWN_BANDS is exhaustive over the
// generated union, so a band added backend-side fails to compile here rather than
// silently passing through.
const KNOWN_BANDS: Record<ConfidenceStatus, true> = {
  established: true,
  provisional: true,
  insufficient: true,
};

export function narrowStatus(s: string | null | undefined): ConfidenceStatus {
  return s != null && Object.prototype.hasOwnProperty.call(KNOWN_BANDS, s)
    ? (s as ConfidenceStatus)
    : "insufficient";
}

export interface BandPresentation {
  /** What the athlete reads. */
  label: string;
  /** Colour classes for the band chip (text + border + background). */
  cls: string;
}

/**
 * How certain the twin is, in words the athlete can act on.
 *
 * The wording is deliberately about EVIDENCE rather than about the engine's mood:
 * "unmeasured" names the thing the athlete can change, where "insufficient" describes an
 * internal state they cannot act on. These are the labels and colours the Assess screen
 * already used for exactly these three literals; this is now their one definition, so
 * Planning and Assess cannot drift into two vocabularies for one band.
 */
export const BAND: Record<ConfidenceStatus, BandPresentation> = {
  established: { label: "measured", cls: "text-mint border-mint/30 bg-mint/[0.06]" },
  provisional: { label: "provisional", cls: "text-warn border-warn/30 bg-warn/[0.06]" },
  insufficient: { label: "unmeasured", cls: "text-hot border-hot/30 bg-hot/[0.06]" },
};

/** Shared chip geometry, so a band looks the same wherever it is rendered. */
export const BAND_CHIP =
  "rounded-full border px-2 py-1 text-[10px] font-semibold leading-none whitespace-nowrap";

/** Ordering for "least certain first" — the axis that should most constrain trust leads. */
export const BAND_RANK: Record<ConfidenceStatus, number> = {
  insufficient: 0,
  provisional: 1,
  established: 2,
};
