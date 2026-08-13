// @vitest-environment jsdom
//
// src/perflab/overlays/logWorkoutRequest.test.tsx
//
// THE REQUEST-BODY INTEGRATION HALF OF THE #199 ORACLE.
//
// The pure suite proves `buildWorkoutLog` is honest; the static guard proves no fixture
// module is reachable from it. Neither proves that the MODAL — the thing an athlete
// actually clicks — hands that honest body to the API client. This renders the real
// component with a real store state and captures the exact object passed to
// `logWorkout`, which is the last frontend artefact before the wire.
//
// FIELD-NAME MAP, asserted explicitly on both sides of the rename:
//     store `checkin.sleepQ` -> WorkoutLog.sleep_quality
//     store `checkin.mood`   -> WorkoutLog.life_stress_inverse
// The renamed field is the one a half-done fix would leave broken, so every case below
// asserts on `life_stress_inverse` by name, never by analogy with sleep.
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { CheckinState } from "../sim";
import type { WorkoutLog } from "@/types";

const AUTH_TOKEN = "test-token";

/** Own-property check. `Object.hasOwn` needs the ES2022 lib; this repo targets ES2020. */
const hasKey = (o: Record<string, unknown>, k: string) =>
  Object.prototype.hasOwnProperty.call(o, k);

/** Every body handed to POST /v1/log-workout during a test. */
const logged: WorkoutLog[] = [];
/** Every body handed to the unauthenticated POST /v1/simulate-dose preview. */
const simulated: WorkoutLog[] = [];

vi.mock("@/auth/useAuth", () => ({
  useAuth: () => ({
    token: AUTH_TOKEN,
    user: { email: "athlete@example.com" },
    profile: null,
    email: "athlete@example.com",
    isGuest: false,
  }),
}));

vi.mock("@/api/perfLabClient", () => ({
  logWorkout: (log: WorkoutLog) => {
    logged.push(log);
    return Promise.resolve({ timestamp: "2026-07-30T00:00:00Z" });
  },
  simulateDose: (log: WorkoutLog) => {
    simulated.push(log);
    return Promise.resolve({ dose_six: null });
  },
  getNextSession: () => Promise.resolve({ exercises: [] }),
  listExercises: () => Promise.resolve([]),
}));

const checkin = (over: Partial<CheckinState> = {}): CheckinState => ({
  hrv: null, sleepH: null, sleepQ: null, rhr: null, soreness: null, mood: null, stress: null, done: false,
  ...over,
});

let storeCheckin: CheckinState = checkin();

vi.mock("../store", () => ({
  usePerfLab: () => ({
    state: {
      logOpen: true,
      logType: "strength",
      rpe: 7,
      durationMin: 42,
      distanceKm: 9,
      checkin: storeCheckin,
      paceSec: 278,
      sim: {},
    },
    actions: {
      closeLog: vi.fn(),
      openAuth: vi.fn(),
      cacheTwinState: vi.fn(),
      applyLog: vi.fn(),
      setRpe: vi.fn(),
      setLogType: vi.fn(),
      setDur: vi.fn(),
      setDist: vi.fn(),
      setPaceSec: vi.fn(),
    },
  }),
}));

// The dose-projection helper reads a much larger slice of state than this test builds;
// the preview panel is not what is under test, so it is stubbed to a fixed vector.
vi.mock("../sim", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../sim")>();
  return {
    ...actual,
    projectLogDose: () => ({
      scaled: [0, 0, 0, 0, 0, 0],
      readyAfter: 60, fatAfter: 30, capDelta: "+1", cap: "Aerobic", zone: "Z3", readyColor: "#fff",
    }),
  };
});

const { LogWorkoutModal } = await import("./LogWorkoutModal");

// The REAL store's initial check-in — deliberately not the local `checkin()` helper.
// The mock above replaces the store for the component, so without this the whole
// integration test would be insulated from the actual seed and would stay green if
// `store.initialState` reintroduced one. This is the link that makes the frontend
// inversion (restore the seed) turn THIS file red.
const realStore = await vi.importActual<typeof import("../store")>("../store");
const REAL_INITIAL_CHECKIN = realStore.initialState().checkin;

beforeEach(() => {
  logged.length = 0;
  simulated.length = 0;
  storeCheckin = checkin();
});
afterEach(cleanup);

/** Render, click "Apply to twin", and return the body handed to `logWorkout`. */
async function submit(ci: CheckinState): Promise<Record<string, unknown>> {
  storeCheckin = ci;
  render(<LogWorkoutModal />);
  fireEvent.click(screen.getByText(/Apply to twin/));
  await vi.waitFor(() => expect(logged.length).toBe(1));
  return logged[0] as unknown as Record<string, unknown>;
}

describe("the object handed to logWorkout (#199)", () => {
  it("NO CHECK-IN: omits sleep_quality AND life_stress_inverse entirely", async () => {
    const b = await submit(REAL_INITIAL_CHECKIN);
    expect(hasKey(b, "sleep_quality"), "sleep_quality must be absent").toBe(false);
    expect(hasKey(b, "life_stress_inverse"), "life_stress_inverse must be absent").toBe(false);
    // And absent on the wire, not merely undefined in the object.
    const wire = JSON.parse(JSON.stringify(b));
    expect(wire).not.toHaveProperty("sleep_quality");
    expect(wire).not.toHaveProperty("life_stress_inverse");
  });

  it("NO CHECK-IN: neither field is 5, 5.5, 7, or 0", async () => {
    const b = await submit(REAL_INITIAL_CHECKIN);
    for (const forbidden of [0, 5, 5.5, 7, 7.5]) {
      expect(b.sleep_quality).not.toBe(forbidden);
      expect(b.life_stress_inverse).not.toBe(forbidden);
    }
  });

  it("COMPLETED CHECK-IN: submits exactly the athlete's values on the 1-10 scale", async () => {
    // sleepQ 5/5 -> 10/10 ; mood 1/5 -> 1/10 (deliberately opposite ends, so a mapper
    // that transposed the two fields would fail rather than coincide).
    const b = await submit(checkin({ sleepQ: 5, mood: 1, done: true }));
    expect(b.sleep_quality).toBe(10);
    expect(b.life_stress_inverse).toBe(1);
  });

  it("NAMING SEAM: the store's `mood` lands in `life_stress_inverse`, not `sleep_quality`", async () => {
    const b = await submit(checkin({ mood: 5, done: true }));
    expect(b.life_stress_inverse, "frontend `mood` must map to backend `life_stress_inverse`").toBe(10);
    expect(hasKey(b, "sleep_quality"), "`mood` must not leak into sleep_quality").toBe(false);
  });

  it("NAMING SEAM: the store's `sleepQ` lands in `sleep_quality`, not `life_stress_inverse`", async () => {
    const b = await submit(checkin({ sleepQ: 5, done: true }));
    expect(b.sleep_quality).toBe(10);
    expect(hasKey(b, "life_stress_inverse")).toBe(false);
  });

  it("PARTIAL: sleep reported, motivation not — one value, one omission", async () => {
    const b = await submit(checkin({ sleepQ: 3, done: true }));
    expect(b.sleep_quality).toBe(5.5);
    expect(hasKey(b, "life_stress_inverse")).toBe(false);
  });

  it("PARTIAL: motivation reported, sleep not", async () => {
    const b = await submit(checkin({ mood: 3, done: true }));
    expect(b.life_stress_inverse).toBe(5.5);
    expect(hasKey(b, "sleep_quality")).toBe(false);
  });

  it("the unauthenticated simulate-dose preview omits them too", async () => {
    // /v1/simulate-dose shares the WorkoutLog schema and must not be broken by the
    // change — nor may it be the surface that reintroduces a fabricated value.
    storeCheckin = REAL_INITIAL_CHECKIN;
    render(<LogWorkoutModal />);
    await vi.waitFor(() => expect(simulated.length).toBeGreaterThan(0));
    const b = simulated[0] as unknown as Record<string, unknown>;
    expect(hasKey(b, "sleep_quality")).toBe(false);
    expect(hasKey(b, "life_stress_inverse")).toBe(false);
  });
});
