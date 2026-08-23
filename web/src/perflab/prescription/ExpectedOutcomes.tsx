// src/perflab/prescription/ExpectedOutcomes.tsx
//
// What the twin predicts this session will do — `why.expected_outcomes`.
//
// DESIGN NOTE, because this is the panel most likely to be misread:
//
// Every axis here is a FATIGUE axis (app/logic/prescription_finalize.py `_OUTCOME_AXES`
// is exactly fatigue_f.{cns,muscular,metabolic,structural,tendon,grip}). Fatigue going UP
// is the ordinary, intended result of training — it is the cost the session is buying,
// not a warning. So the panel is framed as "what this session costs", the horizon string
// is shown rather than hidden, and colour is spent only on movements large enough to mean
// something. A red row against every prescribed session would train the athlete to ignore
// the colour entirely.
//
// The engine emits a point prediction with NO interval, deliberately (the forward model
// is deterministic and these axes carry no variance). Nothing here may draw a band, a
// range or an error bar — that would invent precision the contract refuses to claim.

import { axisLabel } from "./axes";
import { COLORS } from "../viz";
import type { ExpectedOutcome } from "@/types";

/** Matches SimulatorScreen's formatter, including the U+2212 minus. */
const fmtDelta = (n: number): string => `${n >= 0 ? "+" : "−"}${Math.abs(n).toFixed(1)}`;
const fmtValue = (n: number): string => n.toFixed(1);

/**
 * Below this the engine itself calls a movement noise rather than a claim
 * (`MIN_REPORTABLE_DELTA`), so it is shown without colour.
 */
const MEANINGFUL_DELTA = 0.5;

function deltaColor(delta: number): string {
  if (delta > MEANINGFUL_DELTA) return COLORS.hot; // more fatigue — the cost
  if (delta < -MEANINGFUL_DELTA) return COLORS.good; // the session leaves this axis fresher
  return COLORS.dim;
}

function OutcomeRow({ outcome }: { outcome: ExpectedOutcome }) {
  // The track is a RELATION, not a scale: both ends are drawn against a common ceiling so
  // the movement is legible, while the two printed numbers carry the actual truth. No axis
  // is labelled, precisely so the bar is not read as an absolute reading.
  const ceiling = Math.max(outcome.current, outcome.predicted, 1) * 1.15;
  const currentPct = Math.max(0, Math.min(100, (outcome.current / ceiling) * 100));
  const predictedPct = Math.max(0, Math.min(100, (outcome.predicted / ceiling) * 100));
  const from = Math.min(currentPct, predictedPct);
  const width = Math.abs(predictedPct - currentPct);
  const color = deltaColor(outcome.delta);

  return (
    <div className="flex flex-col gap-[7px]">
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-[12px] font-medium leading-none text-mute">{axisLabel(outcome.axis)}</span>
        <span className="flex items-baseline gap-2">
          <span className="font-mono text-[13px] font-semibold leading-none text-soft">
            {fmtValue(outcome.current)}
          </span>
          <span className="text-[11px] font-medium leading-none text-faint">→</span>
          <span className="font-mono text-[13px] font-semibold leading-none" style={{ color }}>
            {fmtValue(outcome.predicted)}
          </span>
          <span className="font-mono text-[10px] leading-none" style={{ color }}>
            ({fmtDelta(outcome.delta)})
          </span>
        </span>
      </div>
      <div className="relative h-[6px] overflow-hidden rounded-full bg-white/[0.07]">
        {/* Where the axis sits now. */}
        <div className="absolute inset-y-0 left-0 rounded-full bg-white/[0.16]" style={{ width: `${currentPct}%` }} />
        {/* What the session moves it by, drawn as the span between the two readings. */}
        <div className="absolute inset-y-0 rounded-full" style={{ left: `${from}%`, width: `${Math.max(width, 1)}%`, background: color }} />
      </div>
    </div>
  );
}

export function ExpectedOutcomes({
  outcomes,
  horizon,
}: {
  outcomes: ExpectedOutcome[];
  horizon?: string | null;
}) {
  if (outcomes.length === 0) return null;

  return (
    <div className="mt-5 border-t border-white/[0.06] pt-[18px]">
      <div className="mb-[14px] flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <div className="font-mono text-[10px] font-semibold uppercase leading-none tracking-[0.14em] text-ac">
          What this session costs
        </div>
        {horizon && <div className="font-mono text-[10px] leading-[1.4] text-dim">{horizon}</div>}
      </div>
      <div className="flex flex-col gap-[13px]">
        {outcomes.map((o, i) => (
          <OutcomeRow key={`${o.axis}-${i}`} outcome={o} />
        ))}
      </div>
    </div>
  );
}
