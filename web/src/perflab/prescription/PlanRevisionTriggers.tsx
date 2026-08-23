// src/perflab/prescription/PlanRevisionTriggers.tsx
//
// What would change this plan — `why.plan_revision_triggers`.
//
// The contract's own framing: a session is "here is your session, AND here is what would
// make it the wrong call". Each trigger is one of the prescriber's real thresholds, so
// this is not a hypothetical — it is the same test that will run tomorrow.
//
// `currently_active` inverts the sentence, and getting that backwards would be a lie:
//   • active   → the driver is firing NOW, so the trigger describes it switching OFF
//                (the constraint lifting, and the plan opening up).
//   • inactive → the driver is not firing, so the trigger describes it switching ON
//                (a new constraint arriving).
// The backend already writes the correct sentence into `condition`; this component
// renders that string rather than composing its own, so the two cannot disagree.

import { COLORS } from "../viz";
import type { PlanRevisionTrigger } from "@/types";

const fmt = (n: number): string => (Number.isInteger(n) ? String(n) : n.toFixed(1));

function TriggerRow({ trigger }: { trigger: PlanRevisionTrigger }) {
  const { current_value: current, threshold, currently_active: active } = trigger;

  // Both readings drawn against one ceiling so "how close is it" is visible. As in
  // ExpectedOutcomes the bar is a relation and the printed numbers are the truth — these
  // axes live on different scales and no single labelled axis would be honest across them.
  const ceiling = Math.max(current, threshold, 1) * 1.25;
  const currentPct = Math.max(0, Math.min(100, (current / ceiling) * 100));
  const thresholdPct = Math.max(0, Math.min(100, (threshold / ceiling) * 100));
  const color = active ? COLORS.warn : COLORS.dim;

  return (
    <div className="flex flex-col gap-[7px]">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-[3px]">
        <span className="flex items-baseline gap-2">
          <span
            className={`rounded-[5px] border px-[6px] py-[3px] font-mono text-[9px] font-semibold uppercase leading-none tracking-[0.08em] ${
              active ? "border-warn/30 bg-warn/[0.10] text-warn" : "border-white/10 bg-white/[0.03] text-dim"
            }`}
          >
            {active ? "applying" : "not applying"}
          </span>
          <span className="text-[12px] font-medium leading-none text-mute">{trigger.label}</span>
        </span>
        <span className="flex items-baseline gap-2">
          <span className="font-mono text-[12.5px] font-semibold leading-none text-soft">{fmt(current)}</span>
          <span className="font-mono text-[10px] leading-none text-dim">/ {fmt(threshold)}</span>
        </span>
      </div>
      <div className="relative h-[6px] overflow-hidden rounded-full bg-white/[0.07]">
        <div className="absolute inset-y-0 left-0 rounded-full" style={{ width: `${currentPct}%`, background: color }} />
        {/* The crossing point. */}
        <div
          className="absolute top-[-2px] h-[10px] w-[2px] rounded-full bg-[#8b919c]"
          style={{ left: `calc(${thresholdPct}% - 1px)` }}
        />
      </div>
      <div className="font-mono text-[10px] leading-[1.45] text-dim">{trigger.condition}</div>
    </div>
  );
}

export function PlanRevisionTriggers({ triggers }: { triggers: PlanRevisionTrigger[] }) {
  if (triggers.length === 0) return null;

  return (
    <div className="mt-5 border-t border-white/[0.06] pt-[18px]">
      <div className="mb-[14px] font-mono text-[10px] font-semibold uppercase leading-none tracking-[0.14em] text-ac">
        What would change this plan
      </div>
      <div className="flex flex-col gap-[15px]">
        {triggers.map((t, i) => (
          <TriggerRow key={`${t.axis}-${i}`} trigger={t} />
        ))}
      </div>
    </div>
  );
}
