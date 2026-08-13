// src/perflab/overlays/workoutLogBody.test.ts
//
// THE BEHAVIOURAL HALF OF THE WORKOUT-LOG HONESTY ORACLE (#199).
//
// The static guard (workoutLogBoundary.test.ts) proves no fixture MODULE is reachable
// from the request-body builder. It cannot prove that a fabricated VALUE never reaches
// the body — a seed plumbed through the store, a parameter, or a literal would pass it
// untouched, which is exactly how `sleepQ: 4` / `mood: 4` shipped. This file tests the
// other property: across the full product of check-in states, no value the athlete did
// not enter can appear in a submitted body.
//
// Neither test substitutes for the other, which is why both are required.
//
// FIELD-NAME MAP (frontend -> backend), because the two differ and the matrix must be
// proven against the real names on each side:
//     store `checkin.sleepQ` (1-5)  ->  WorkoutLog.sleep_quality       (1-10)
//     store `checkin.mood`   (1-5)  ->  WorkoutLog.life_stress_inverse (1-10)
// "Motivation"/`mood` is the frontend label; `life_stress_inverse` is the backend field
// it lands in (10 = no life stress).
import { describe, expect, it } from "vitest";
import type { CheckinState } from "../sim";
import { initialState } from "../store";
import {
  buildWorkoutLog,
  checkinToWorkoutWellness,
  fromFive,
  NO_WELLNESS_REPORTED,
  type WorkoutWellness,
} from "./workoutLogBody";

/** The exact sample constants the store used to seed `checkin` with (store.tsx:206,
 *  pre-#199). None of them may reach a request body by any route. */
const LEGACY_SEED = { hrv: 64, sleepH: 7.5, sleepQ: 4, rhr: 52, soreness: "mild", mood: 4, stress: 2 } as const;

const checkin = (over: Partial<CheckinState> = {}): CheckinState => ({
  hrv: null, sleepH: null, sleepQ: null, rhr: null, soreness: null, mood: null, stress: null, done: false,
  ...over,
});

const body = (wellness: WorkoutWellness) =>
  buildWorkoutLog("tempo", 7, 42, 9, wellness, []) as Record<string, unknown>;

/** Own-property check. `Object.hasOwn` needs the ES2022 lib; this repo targets ES2020
 *  (tsconfig.json), and widening the lib for a test would be the tail wagging the dog. */
const hasKey = (o: Record<string, unknown>, k: string) =>
  Object.prototype.hasOwnProperty.call(o, k);

/** Every value a 1-5 slider can hold, plus "not reported". */
const SLIDER_STATES = [null, 1, 2, 3, 4, 5] as const;

// ---- The default state: nothing entered ------------------------------------------

describe("REGRESSION #199: the seeded store defaults cannot be persisted", () => {
  it("the store no longer seeds any check-in value", () => {
    const ci = initialState().checkin;
    expect(ci).toEqual({
      hrv: null, sleepH: null, sleepQ: null, rhr: null, soreness: null, mood: null, stress: null, done: false,
    });
    // Named explicitly so a reintroduced seed fails by name, not just by shape.
    expect(ci.sleepQ, "sleepQ must start not-reported, not 4").toBeNull();
    expect(ci.mood, "mood must start not-reported, not 4").toBeNull();
  });

  it("a workout logged from the untouched store carries NO wellness keys", () => {
    const b = body(checkinToWorkoutWellness(initialState().checkin));
    expect(hasKey(b, "sleep_quality")).toBe(false);
    expect(hasKey(b, "life_stress_inverse")).toBe(false);
  });

  it("no legacy seed constant reaches either wellness field", () => {
    // Asserted on the PARSED wellness fields, not a substring of the whole body: "4"
    // and "2" occur legitimately inside the timestamp and the duration, so a raw
    // substring scan would be both flaky and meaningless.
    const b = JSON.parse(JSON.stringify(body(checkinToWorkoutWellness(initialState().checkin))));
    for (const [name, value] of Object.entries(LEGACY_SEED)) {
      expect(b.sleep_quality, `legacy seed ${name}=${value} leaked into sleep_quality`).not.toBe(value);
      expect(b.life_stress_inverse, `legacy seed ${name}=${value} leaked into life_stress_inverse`).not.toBe(value);
    }
    expect(b.sleep_quality).toBeUndefined();
    expect(b.life_stress_inverse).toBeUndefined();
  });

  it("the legacy seed is gone from the store itself, by value", () => {
    // Belt and braces: even if some future mapper reintroduced a path, there would be
    // no seeded number left in the store for it to read.
    const ci = initialState().checkin as unknown as Record<string, unknown>;
    for (const [field, value] of Object.entries(LEGACY_SEED)) {
      expect(ci[field], `store still seeds checkin.${field} = ${value}`).not.toBe(value);
      expect(ci[field]).toBeNull();
    }
  });

  it("`done` does not resurrect a value: completing an empty check-in still omits both", () => {
    // The store's `applyCheckin` only flips `done` (store.tsx:384-391); it never sets a
    // value. Gating on `done` was therefore never sufficient, and nothing here uses it.
    const b = body(checkinToWorkoutWellness(checkin({ done: true })));
    expect(hasKey(b, "sleep_quality")).toBe(false);
    expect(hasKey(b, "life_stress_inverse")).toBe(false);
  });

  it("PARTIAL CHECK-IN: moving one slider does not submit a value for the other", () => {
    // The precise failure `done`-gating would have missed: one slider moved, the other
    // still holding a seed, `done === true`.
    const b = body(checkinToWorkoutWellness(checkin({ sleepQ: 5, done: true })));
    expect(b.sleep_quality).toBe(10);
    expect(hasKey(b, "life_stress_inverse")).toBe(false);
  });
});

// ---- State-product sweep ----------------------------------------------------------

describe("state-product sweep: every check-in state maps honestly", () => {
  it("covers the full product of both sliders", () => {
    let checked = 0;
    for (const sleepQ of SLIDER_STATES) {
      for (const mood of SLIDER_STATES) {
        const b = body(checkinToWorkoutWellness(checkin({ sleepQ, mood, done: true })));
        const label = `sleepQ=${sleepQ} mood=${mood}`;

        if (sleepQ === null) {
          expect(hasKey(b, "sleep_quality"), `${label}: unknown sleep must be OMITTED`).toBe(false);
        } else {
          expect(b.sleep_quality, `${label}: reported sleep must be the athlete's value`).toBe(fromFive(sleepQ));
        }

        if (mood === null) {
          expect(hasKey(b, "life_stress_inverse"), `${label}: unknown mood must be OMITTED`).toBe(false);
        } else {
          expect(b.life_stress_inverse, `${label}: reported mood must be the athlete's value`).toBe(fromFive(mood));
        }
        checked++;
      }
    }
    expect(checked).toBe(SLIDER_STATES.length ** 2);
  });

  it("an omitted field is absent, not null-valued and not zero", () => {
    const b = body(NO_WELLNESS_REPORTED);
    // `undefined` would serialize away too, but the key must not exist at all so the
    // wire body is unambiguous.
    expect("sleep_quality" in b).toBe(false);
    expect(JSON.parse(JSON.stringify(b))).not.toHaveProperty("sleep_quality");
    expect(JSON.parse(JSON.stringify(b))).not.toHaveProperty("life_stress_inverse");
  });

  it("NEVER a midpoint or zero for unknown", () => {
    const serialized = JSON.stringify(body(NO_WELLNESS_REPORTED));
    for (const forbidden of ["sleep_quality", "life_stress_inverse"]) {
      expect(serialized).not.toContain(forbidden);
    }
  });

  it("the other four check-in signals never reach the workout log at all", () => {
    // Only sleep quality and motivation map to WorkoutLog fields. If a future edit
    // widened the mapping, this catches it before the value ships.
    //
    // Asserted on PARSED values, not a substring of the serialized body: `:5` also
    // occurs inside the ISO timestamp roughly a sixth of the time, which made an
    // earlier substring version of this test fail on the clock rather than on a leak.
    const loud = checkin({ hrv: 200, sleepH: 12, rhr: 30, soreness: "high", stress: 5, done: true });
    const b = JSON.parse(JSON.stringify(body(checkinToWorkoutWellness(loud))));
    expect(hasKey(b, "sleep_quality"), "sleepQ unreported: must stay absent").toBe(false);
    expect(hasKey(b, "life_stress_inverse"), "mood unreported: must stay absent").toBe(false);
    const values = Object.values(b);
    for (const v of [200, 12, 30, 5]) {
      expect(values, `unrelated check-in signal ${v} leaked into the body`).not.toContain(v);
    }
  });
});

// ---- Scale mapping ----------------------------------------------------------------

describe("fromFive: the 1-5 slider maps onto the backend's 1-10 scale", () => {
  it("preserves not-reported", () => {
    expect(fromFive(null)).toBeNull();
  });

  it("anchors both endpoints", () => {
    expect(fromFive(1)).toBe(1);
    expect(fromFive(5)).toBe(10);
  });

  it("is monotone increasing and stays inside the backend's [1, 10] bounds", () => {
    const mapped = [1, 2, 3, 4, 5].map((v) => fromFive(v) as number);
    expect(mapped).toEqual([...mapped].sort((a, b) => a - b));
    expect(new Set(mapped).size).toBe(mapped.length);
    for (const m of mapped) {
      expect(m).toBeGreaterThanOrEqual(1);
      expect(m).toBeLessThanOrEqual(10);
    }
  });

  it("maps the middle of one scale to the middle of the other", () => {
    expect(fromFive(3)).toBe(5.5);
  });

  it("never emits 0, and 0 is not how unknown is spelled", () => {
    for (const v of SLIDER_STATES) {
      expect(fromFive(v)).not.toBe(0);
    }
    expect(fromFive(null)).toBeNull();
    expect(fromFive(1)).not.toBeNull();
  });
});

// ---- Reported values survive exactly ----------------------------------------------

describe("a real athlete-entered value is submitted, exactly", () => {
  it.each([1, 2, 3, 4, 5])("sleepQ=%i round-trips to sleep_quality", (v) => {
    const b = body(checkinToWorkoutWellness(checkin({ sleepQ: v, done: true })));
    expect(b.sleep_quality).toBe(fromFive(v));
  });

  it.each([1, 2, 3, 4, 5])("mood=%i round-trips to life_stress_inverse", (v) => {
    const b = body(checkinToWorkoutWellness(checkin({ mood: v, done: true })));
    expect(b.life_stress_inverse).toBe(fromFive(v));
  });

  it("the non-wellness body is unchanged by the wellness state", () => {
    const withNone = body(NO_WELLNESS_REPORTED);
    const withBoth = body(checkinToWorkoutWellness(checkin({ sleepQ: 3, mood: 3 })));
    for (const key of ["modality", "duration_minutes", "session_rpe", "distance_meters"]) {
      expect(withBoth[key]).toEqual(withNone[key]);
    }
  });
});
