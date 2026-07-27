// @vitest-environment jsdom
//
// The body-map is now rendered by BOTH twin bodies, so the two differences that
// used to be baked into two separate copies are the claims worth pinning:
// where the numbers come from, and whether a row is interactive. If the live
// path ever silently acquired the guest's click handler — or the guest path
// lost it — these fail.

import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { COLORS, TISSUE_ORDER } from "../../sim";
import { TissueBodyMap } from "./TissueBodyMap";

afterEach(cleanup);

/** The region's label <span> — the element carrying the threshold colour. */
const labelFor = (label: string) => screen.getByText(label);
/** The row <div> wrapping a region's swatch, label and value. */
const rowFor = (label: string) => labelFor(label).parentElement as HTMLElement;
/** jsdom normalises inline colours to rgb(), so compare through the same normaliser. */
const asRendered = (hex: string) => {
  const probe = document.createElement("span");
  probe.style.color = hex;
  return probe.style.color;
};

describe("region values", () => {
  it("renders every region in TISSUE_ORDER, reading each value through getT", () => {
    const seen: string[] = [];
    render(
      <TissueBodyMap
        getT={(label) => {
          seen.push(label);
          return 30;
        }}
      />,
    );

    for (const label of TISSUE_ORDER) {
      expect(screen.getByText(label)).toBeDefined();
      expect(seen).toContain(label);
    }
  });

  it("renders the value the caller supplied, not a default", () => {
    const values: Record<string, number> = { Knee: 71, Lumbar: 12 };
    render(<TissueBodyMap getT={(label) => values[label] ?? 0} />);

    expect(rowFor("Knee").textContent).toContain("71");
    expect(rowFor("Lumbar").textContent).toContain("12");
  });

  it("marks a region at or above the 45 threshold differently from one below it", () => {
    render(<TissueBodyMap getT={(label) => (label === "Knee" ? 45 : 44)} />);

    expect(labelFor("Knee").style.color).toBe(asRendered(COLORS.soft));
    expect(labelFor("Lumbar").style.color).toBe(asRendered(COLORS.mute));
    expect(labelFor("Knee").style.color).not.toBe(labelFor("Lumbar").style.color);
  });
});

describe("interactivity", () => {
  it("is inert with no pointer cursor when no handler is given (the live path)", () => {
    render(<TissueBodyMap getT={() => 30} />);

    const row = rowFor("Knee");
    expect(row.className).not.toContain("cursor-pointer");
    // Nothing to assert a call against — the point is that clicking does nothing.
    fireEvent.click(row);
  });

  it("calls the handler with the region label when one is given (the guest path)", () => {
    const onRegionClick = vi.fn();
    render(<TissueBodyMap getT={() => 30} onRegionClick={onRegionClick} />);

    const row = rowFor("Lumbar");
    expect(row.className).toContain("cursor-pointer");

    fireEvent.click(row);
    expect(onRegionClick).toHaveBeenCalledTimes(1);
    expect(onRegionClick).toHaveBeenCalledWith("Lumbar");
  });
});
