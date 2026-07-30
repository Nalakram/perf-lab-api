// src/perflab/overlays/workoutLogBody.ts
//
// THE ONLY PLACE A `POST /v1/log-workout` (and `/v1/simulate-dose`) REQUEST BODY IS
// BUILT (#199).
//
// It lives in its own module, separate from LogWorkoutModal.tsx, for one structural
// reason: the modal legitimately value-imports the fixture module `../sim` for its
// preview chrome (COLORS, DOSE_NAMES, doseBarColor, PRESETS, projectLogDose), so a
// static reachability guard rooted at the modal could never be green. Rooted HERE the
// guard is meaningful and enforceable — see workoutLogBoundary.test.ts. Keep this
// module free of value imports from any fixture module; `import type` is fine, because
// a type-only edge is erased at build time and carries no data.
//
// The honesty contract this module exists to hold:
//
//   real athlete-entered value  -> submit it
//   not entered / unknown       -> OMIT the key entirely
//   guest / sample state        -> unreachable from here
//   zero or a neutral midpoint  -> NEVER used to mean unknown
//
// The backend half (ADR-0049) makes `sleep_quality` / `life_stress_inverse` genuinely
// nullable: absent means "no check-in exists", is stored as SQL NULL, and contributes a
// LABELLED neutral (no dose penalty, zero confidence) instead of the old imputed 5.0.
// Omitting the key is therefore the correct wire encoding for "not reported" — it is
// not a way of dodging a required field. The regenerated contract confirms it:
// `sleep_quality?: number | null` in src/types.gen.ts, and neither field appears in
// WorkoutLog's `required` list.
import type { Modality, WorkoutLog } from "@/types";
import type { CheckinState } from "../sim";
import { deriveModality, groupsToSets, type SetGroup } from "./setBuilderLogic";

/**
 * The two wellness readings the workout log carries, on the BACKEND's 1–10 scale.
 * `null` means the athlete has not reported it — it is never a number standing in for
 * "unknown".
 */
export interface WorkoutWellness {
  /** 1 = worst sleep, 10 = best. null = not reported. */
  sleepQuality: number | null;
  /** 1 = very high life stress, 10 = none. null = not reported. */
  lifeStressInverse: number | null;
}

/** A wellness report in which nothing has been entered. The default, always. */
export const NO_WELLNESS_REPORTED: WorkoutWellness = {
  sleepQuality: null,
  lifeStressInverse: null,
};

/**
 * Map a check-in's 1–5 slider onto the backend's 1–10 scale, preserving "not reported".
 *
 * The endpoints anchor: 1 -> 1 and 5 -> 10, linearly, so `v -> 1 + (v - 1) * 9/4`.
 * (3/5 -> 5.5/10, the true middle of both scales.)
 *
 * This rescaling is also a bug fix. The previous code sent the raw 1–5 slider value
 * into a field the backend bounds to [1, 10] and scores against
 * `dose_human_factor_reference = 5.0`, so a 4/5 ("good") sleep arrived as 4/10 ("poor")
 * and earned a real dose penalty, and `mood` — capped at 5 — could never clear the
 * reference at all. It validated silently because [1,5] is inside [1,10]. The sibling
 * wellness path never had this bug: `wellnessSignals.metricValue` already rescales
 * (`sleepQ * 20` for the 0–100 field).
 */
export function fromFive(v: number | null): number | null {
  if (v === null) return null;
  return 1 + ((v - 1) * 9) / 4;
}

/**
 * The wellness a workout log may carry, derived from the morning check-in.
 *
 * Pure and total: a check-in in which nothing was entered yields
 * `NO_WELLNESS_REPORTED`, because every `CheckinState` self-report starts as `null`
 * (`store.initialState`). There is no seeded constant left for this to read.
 */
export function checkinToWorkoutWellness(c: CheckinState): WorkoutWellness {
  return {
    sleepQuality: fromFive(c.sleepQ),
    lifeStressInverse: fromFive(c.mood),
  };
}

/** Build a backend WorkoutLog from the modal's form state.
 *
 * When per-set groups are present (ADR-0045) they are the record: `sets` is sent,
 * the session modality is derived from them (the backend derives it too), and the
 * running-shaped session distance is dropped so the backend rolls it up from sets. */
export function buildWorkoutLog(
  logType: string,
  rpe: number,
  durationMin: number,
  distanceKm: number,
  wellness: WorkoutWellness,
  setGroups: SetGroup[] = [],
): WorkoutLog {
  const sets = groupsToSets(setGroups);
  const modality: Modality =
    (sets.length ? deriveModality(setGroups) : null) ??
    (logType === "strength" ? "Strength" : "Running");
  // We send only what the form captures; the backend fills server-side defaults
  // for omitted fields (is_benchmark, novelty, total_volume_load, …). `satisfies`
  // still type-checks the fields we DO set against the contract; the cast covers
  // the server-defaulted remainder.
  return {
    timestamp: new Date().toISOString(),
    modality,
    duration_minutes: durationMin,
    session_rpe: rpe,
    // Wellness is OMITTED, not defaulted, when the athlete has not reported it. The
    // key is absent from the JSON body entirely — the backend then records SQL NULL
    // and applies a labelled neutral rather than a fabricated midpoint (ADR-0049).
    ...(wellness.sleepQuality !== null ? { sleep_quality: wellness.sleepQuality } : {}),
    ...(wellness.lifeStressInverse !== null
      ? { life_stress_inverse: wellness.lifeStressInverse }
      : {}),
    ...(sets.length
      ? { sets }
      : modality === "Running"
        ? { distance_meters: Math.round(distanceKm * 1000) }
        : {}),
  } satisfies Partial<WorkoutLog> as WorkoutLog;
}
