// src/perflab/readinessPresentation.ts
//
// How a readiness number is PRESENTED — colour, word, advisory sentence. Nothing
// here fabricates, measures, or derives a readiness value; every function takes a
// number someone else is responsible for and maps it to display copy.
//
// These four symbols used to live in `sim.ts` alongside `DAYS`, `buildCheckin`,
// `CAP_CFG`, `SKILL_DEFS` and `PHASES`. That co-location was the problem: a screen
// that only wanted the palette had to import the fixture module to get it, which
// made "does this file reach sample data?" unanswerable by looking at imports.
// With them extracted, `sim.ts` is categorically fixture-bearing and an import of
// it means what it says.
//
// DEPENDENCY DIRECTION IS ONE-WAY (map #182, #189a): this module must never import
// `sim.ts`, guest-preview modules, or any fixture store. `sim.ts` may import this.
// The rule is enforced mechanically by the static boundary guard, not by comment.
import { COLORS } from "./viz/tokens";

export { COLORS };

/** Palette colour for a readiness number (0–100). */
export const readinessColor = (r: number) =>
  r >= 75 ? COLORS.good : r >= 55 ? COLORS.lime : r >= 40 ? COLORS.warn : COLORS.hot;

/** One-word reading of a readiness number. */
export const readinessWord = (r: number) => (r >= 75 ? "Fresh" : r >= 55 ? "Moderate" : r >= 40 ? "Low" : "Crashed");

/** Advisory sentence for a readiness number. */
export const readinessNote = (r: number) =>
  r >= 75
    ? "Fully recovered — green light for a quality or volume block."
    : r >= 55
      ? "Hold intensity; full quality session viable in ~24h."
      : r >= 40
        ? "Prioritise easy volume or recovery; defer hard efforts."
        : "Recovery only — systemic and tissue load elevated.";
