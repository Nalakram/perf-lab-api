// src/perflab/screens/goalChipsView.ts
//
// View model for Settings' multi-goal chip grid — the reference example of the
// SECOND sanctioned way to consume the canonical resource contract: an
// exhaustive switch, for surfaces that are not card-shaped and so cannot use
// <ResourceState>.
//
// Pure and separately testable, because the claim that matters here is not
// visual: toggling a chip bumps objectivesRefreshKey, which refetches, and the
// previously lit chips must stay lit through that refetch instead of all
// flashing off at once. A failed refresh must keep them lit as well, while
// saying plainly that the set is the last one loaded rather than freshly
// confirmed.
import { assertNever, type AuthedResource } from "../resource";
import type { ObjectiveRead } from "@/types";

export interface GoalChipsView {
  /** Objectives whose domains light a chip. Empty only when none are known. */
  objectives: ObjectiveRead[];
  note: string | null;
  noteTone: "faint" | "hot";
  showGrid: boolean;
  /** False whenever toggling would act on an unknown or unauthenticated set. */
  interactive: boolean;
}

export function goalChipsView(resource: AuthedResource<ObjectiveRead[]>): GoalChipsView {
  switch (resource.status) {
    case "guest":
      return {
        objectives: [],
        note: "Sign in to train for more than one goal.",
        noteTone: "faint",
        showGrid: false,
        interactive: false,
      };

    case "loading":
      // No usable set yet — unlit chips are honest, but they must not be
      // toggleable, or a toggle would compute priority from an unknown set.
      return {
        objectives: [],
        note: "Loading your goals…",
        noteTone: "faint",
        showGrid: true,
        interactive: false,
      };

    case "error":
      return {
        objectives: [],
        note: `Couldn't load your goals — ${resource.error.message}`,
        noteTone: "hot",
        showGrid: true,
        interactive: false,
      };

    case "success":
      return {
        objectives: resource.data,
        note:
          resource.refresh.status === "error"
            ? "Couldn't refresh your goals — these chips show your last loaded set."
            : null,
        noteTone: "hot",
        showGrid: true,
        interactive: true,
      };

    default:
      return assertNever(resource);
  }
}
