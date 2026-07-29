// @vitest-environment jsdom
//
// The radar's spoke labels live OUTSIDE the value ring, and an <svg> root clips to
// its viewport. Before `labelPad`, the two near-horizontal spokes (index 1 and 4 of
// five) started ~22 user units from the viewBox edge while their labels need ~27–31,
// so "Glyco" rendered as "Glyc" and "Work" lost its leading W — invisible to tsc,
// to vitest, and to any snapshot that doesn't measure geometry.
//
// jsdom has no text metrics, so width is ESTIMATED at 0.62em per character — wide
// enough to cover the mixed-case labels this component actually receives. The test
// is therefore a bound, not a measurement, and it is deliberately loose in the
// direction that avoids false failures.
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Radar, type RadarAxis } from "./Radar";

const AXES: RadarAxis[] = [
  { key: "aerobic", label: "Aerobic", value: 420, max: 650 },
  { key: "glycolytic", label: "Glyco*", value: 62, max: 100 },
  { key: "max_strength", label: "Strength", value: 71, max: 100 },
  { key: "power", label: "Power", value: 55, max: 100 },
  { key: "work_capacity", label: "Work*", value: 48, max: 100 },
];

const CHAR_W = 0.62;
const FONT_SIZE = 10;

function labelExtent(text: SVGTextElement) {
  const x = Number(text.getAttribute("x"));
  const w = (text.textContent ?? "").length * CHAR_W * FONT_SIZE;
  switch (text.getAttribute("text-anchor")) {
    case "start":
      return { left: x, right: x + w };
    case "end":
      return { left: x - w, right: x };
    default:
      return { left: x - w / 2, right: x + w / 2 };
  }
}

describe("Radar spoke labels", () => {
  it("keeps every label inside the viewBox at the size the Twin uses", () => {
    const { container } = render(<Radar axes={AXES} size={200} />);
    const svg = container.querySelector("svg");
    expect(svg).not.toBeNull();

    const [minX, , width] = (svg!.getAttribute("viewBox") ?? "")
      .split(/\s+/)
      .map(Number);
    const maxX = minX + width;

    const texts = Array.from(svg!.querySelectorAll("text")) as SVGTextElement[];
    expect(texts).toHaveLength(AXES.length);

    const clipped = texts
      .map((t) => ({ label: t.textContent, ...labelExtent(t) }))
      .filter((e) => e.left < minX || e.right > maxX);

    expect(clipped).toEqual([]);
  });

  it("renders one label per axis, unabbreviated", () => {
    const { container } = render(<Radar axes={AXES} size={200} />);
    const labels = Array.from(container.querySelectorAll("text")).map((t) => t.textContent);
    expect(labels).toEqual(["Aerobic", "Glyco*", "Strength", "Power", "Work*"]);
  });
});
