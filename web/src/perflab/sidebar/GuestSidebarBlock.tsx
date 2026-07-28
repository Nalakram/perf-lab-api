// src/perflab/sidebar/GuestSidebarBlock.tsx
//
// The GUEST sidebar block card: a sample block carrying the same persistent
// provenance label as every other guest surface.
//
// Before B5's browser gate these same three values ("Mid-base", 42%,
// "Week 3 of 7") were rendered to guests with NO badge, while the guest
// Overview badged readiness, this-morning, the trend and the twin snapshot.
// The values are unchanged for guests — only their provenance is now stated.
import { SampleTag } from "../SampleTag";
import { Track } from "../ui";

/** The sample program shown to guests. Deliberately local and clearly labelled. */
const SAMPLE_BLOCK = { label: "Mid-base", pct: 42, weekLine: "Week 3 of 7 · build phase" };

export function GuestSidebarBlock() {
  return (
    <div className="rounded-[13px] border border-white/[0.07] bg-white/[0.02] p-[13px]">
      <div className="flex items-center justify-between gap-2">
        <span className="font-mono text-[10px] font-semibold uppercase leading-none tracking-[0.14em] text-faint">
          Block
        </span>
        <SampleTag />
      </div>
      <div className="mt-[9px] flex items-center justify-between gap-2">
        <span className="font-mono text-[11px] font-semibold leading-none text-ac">
          {SAMPLE_BLOCK.label}
        </span>
      </div>
      <div className="mt-[10px]">
        <Track
          pct={SAMPLE_BLOCK.pct}
          background="linear-gradient(90deg,var(--ac),#7bd6c0)"
          className="h-[5px]"
        />
      </div>
      <div className="mt-2 text-[11px] font-medium leading-[1.3] text-faint">
        {SAMPLE_BLOCK.weekLine}
      </div>
    </div>
  );
}
