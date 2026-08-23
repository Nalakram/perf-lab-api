// @vitest-environment jsdom
//
// The rules this component must not break, all of them honesty rules rather than
// layout ones:
//   • evidence REPLACES the driver phrases, never doubles them — the two carry the
//     same drivers, and rendering both reads as twice the evidence;
//   • a missing per-axis confidence band means the engine models no uncertainty for
//     that axis, which is UNKNOWN certainty, so nothing may be shown;
//   • families with no variance are named out loud rather than left silent.
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { WhyThisSession } from "./WhyThisSession";
import type { StateEvidence, WorkoutPrescription } from "@/types";

afterEach(cleanup);

type Why = NonNullable<WorkoutPrescription["why"]>;

const why = (over: Partial<Why> = {}): Why => ({ ...over }) as Why;

const evidence = (over: Partial<StateEvidence> = {}): StateEvidence =>
  ({
    axis: "f_nm_central",
    label: "elevated CNS / central fatigue",
    value: 62.4,
    threshold: 55,
    direction: "above",
    ...over,
  }) as StateEvidence;

describe("WhyThisSession", () => {
  it("renders nothing at all when there is no explanation", () => {
    const { container } = render(<WhyThisSession why={undefined} />);
    expect(container.innerHTML).toBe("");
  });

  it("renders nothing when the explanation carries no readable content", () => {
    const { container } = render(<WhyThisSession why={why({ state_drivers: [], constraints_applied: [] })} />);
    expect(container.innerHTML).toBe("");
  });

  it("shows the driver phrases when the payload carries no structured evidence", () => {
    render(<WhyThisSession why={why({ state_drivers: ["elevated CNS / central fatigue"] })} />);
    expect(screen.getByText("elevated CNS / central fatigue")).toBeTruthy();
  });

  it("shows evidence INSTEAD OF the phrases, never both", () => {
    render(
      <WhyThisSession
        why={why({
          state_drivers: ["elevated CNS / central fatigue"],
          state_evidence: [evidence()],
        })}
      />,
    );
    // One occurrence — the evidence row — not two.
    expect(screen.getAllByText("elevated CNS / central fatigue")).toHaveLength(1);
    // ...and it carries the reading and threshold the phrase alone could not.
    expect(screen.getByText("62.4")).toBeTruthy();
    expect(screen.getByText(/55/)).toBeTruthy();
  });

  it("shows no certainty chip for an axis the engine models no variance for", () => {
    render(<WhyThisSession why={why({ state_evidence: [evidence({ confidence_status: null })] })} />);
    expect(screen.queryByText("measured")).toBeNull();
    expect(screen.queryByText("provisional")).toBeNull();
    expect(screen.queryByText("unmeasured")).toBeNull();
  });

  it("shows the band when the axis does carry one", () => {
    render(<WhyThisSession why={why({ state_evidence: [evidence({ confidence_status: "provisional" })] })} />);
    expect(screen.getByText("provisional")).toBeTruthy();
  });

  it("states the families carrying no modelled uncertainty rather than staying silent", () => {
    render(
      <WhyThisSession
        why={why({
          confidence: {
            policy_version: "v1",
            capacity_axes: { aerobic: "provisional" },
            uncertainty_not_modelled: ["fatigue_f", "tissue_t"],
          },
        })}
      />,
    );
    expect(screen.getByText(/No uncertainty modelled for/)).toBeTruthy();
    expect(screen.getByText(/unknown certainty, not high certainty/)).toBeTruthy();
  });

  it("renders the weakest axis with its band, so the constraint on trust is named", () => {
    render(
      <WhyThisSession
        why={why({
          confidence: {
            policy_version: "v1",
            weakest_capacity_axis: "max_strength",
            weakest_capacity_status: "insufficient",
          },
        })}
      />,
    );
    expect(screen.getByText("Max strength")).toBeTruthy();
    expect(screen.getByText("unmeasured")).toBeTruthy();
  });

  it("survives a confidence band this build has never heard of", () => {
    render(
      <WhyThisSession
        why={why({
          confidence: {
            policy_version: "v1",
            capacity_axes: { aerobic: "wildly_confident" as never },
          },
        })}
      />,
    );
    // Degrades to the conservative band rather than rendering an unknown word.
    expect(screen.getByText(/unmeasured/)).toBeTruthy();
  });
});
