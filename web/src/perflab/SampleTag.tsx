// src/perflab/SampleTag.tsx
//
// The persistent guest-provenance label, shared by every sample surface.
//
// It lives in its own neutral module (rather than inside GuestOverviewPreview)
// so that a guest surface elsewhere in the app — e.g. the sidebar's block card —
// can carry identical provenance without importing a fixture module. Importing
// GuestOverviewPreview to reuse its badge would drag `sim.ts` along with it and
// trip the authenticated-reachability guard.
export const SAMPLE_BADGE = "Sample data";

/** The persistent provenance label. Rendered per section, not once at the top. */
export function SampleTag() {
  return (
    <span className="rounded-[5px] border border-mint/25 bg-mint/[0.08] px-[6px] py-[3px] font-mono text-[9px] font-semibold uppercase leading-none tracking-[0.1em] text-[#9ad6c8]">
      {SAMPLE_BADGE}
    </span>
  );
}
