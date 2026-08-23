// src/perflab/prescription/WhyThisSession.tsx
//
// The live prescription explanation, shared by Planning and Twin.
//
// It used to live inside PlanningScreen and render three string lists. Twin fetched the
// same `WorkoutPrescription` and dropped `why` entirely, so the same athlete got a
// reasoned session on one screen and a bare one on the other. Extracting it is what makes
// the two agree; the structure below is what the string lists could not carry.
//
// The shape change that matters: `why.state_drivers` is a list of PHRASES, while
// `why.state_evidence` is the same tests carrying the number and threshold that fired
// them (app/logic/prescription_finalize.py `_DRIVER_RULES` builds both from one row).
// When evidence is present it is rendered instead of the phrases — never alongside, or
// the athlete reads the same driver twice. The phrases remain the fallback, because a
// prescription built without athlete state carries drivers and no evidence.

import { axisLabel as axisLabelOf, BAND, BAND_CHIP, narrowStatus } from "./axes";
import type { PrescriptionConfidence, StateEvidence, WorkoutPrescription } from "@/types";

/** Two-space-tolerant number formatting: thresholds are round, readings usually are not. */
const fmt = (n: number): string => (Number.isInteger(n) ? String(n) : n.toFixed(1));

function WhySection({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="mb-[6px] font-mono text-[9.5px] font-semibold uppercase leading-none tracking-[0.12em] text-faint">
        {label}
      </div>
      {children}
    </div>
  );
}

/**
 * One threshold test, with the reading that fired it.
 *
 * `confidence_status` being absent is NOT high certainty — the engine models no variance
 * for fatigue, tissue or skill at all — so a missing band renders no chip rather than an
 * optimistic one. That asymmetry is the whole point of the field.
 */
function EvidenceRow({ ev }: { ev: StateEvidence }) {
  const band = ev.confidence_status == null ? null : BAND[narrowStatus(ev.confidence_status)];
  return (
    <li className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-[3px]">
      <span className="text-[12.5px] font-medium leading-[1.5] text-mute">{ev.label}</span>
      <span className="flex items-baseline gap-2">
        <span className="font-mono text-[12px] font-semibold leading-none text-soft">{fmt(ev.value)}</span>
        <span className="font-mono text-[10px] leading-none text-dim">
          {ev.direction === "above" ? "＞" : "＜"} {fmt(ev.threshold)}
        </span>
        {band && <span className={`${BAND_CHIP} ${band.cls}`}>{band.label}</span>}
      </span>
    </li>
  );
}

/**
 * What the plan was built on, and how sure the twin is of it.
 *
 * Reports the families the engine keeps NO uncertainty for, rather than letting their
 * silence read as confidence — the backend sends `uncertainty_not_modelled` precisely so
 * that absence is stated out loud.
 */
function ConfidenceBlock({ confidence }: { confidence: PrescriptionConfidence }) {
  const axes = Object.entries(confidence.capacity_axes ?? {});
  const weakest = confidence.weakest_capacity_axis;
  const weakestBand =
    confidence.weakest_capacity_status == null
      ? null
      : BAND[narrowStatus(confidence.weakest_capacity_status)];
  const notModelled = confidence.uncertainty_not_modelled ?? [];

  if (axes.length === 0 && weakest == null && notModelled.length === 0) return null;

  return (
    <WhySection label="Certainty of the state behind this">
      <div className="flex flex-col gap-[8px]">
        {weakest != null && weakestBand && (
          <div className="text-[12.5px] font-medium leading-[1.5] text-mute">
            Least certain axis:{" "}
            <span className="font-semibold text-soft">{axisLabelOf(weakest)}</span>{" "}
            <span className={`${BAND_CHIP} ${weakestBand.cls} ml-[2px] align-[1px]`}>{weakestBand.label}</span>
          </div>
        )}
        {axes.length > 0 && (
          <div className="flex flex-wrap gap-[5px]">
            {axes.map(([axis, status]) => {
              const band = BAND[narrowStatus(status)];
              return (
                <span key={axis} className={`${BAND_CHIP} ${band.cls}`}>
                  {axisLabelOf(axis)} · {band.label}
                </span>
              );
            })}
          </div>
        )}
        {notModelled.length > 0 && (
          <div className="font-mono text-[10px] leading-[1.5] text-dim">
            No uncertainty modelled for {notModelled.map(axisLabelOf).join(", ").toLowerCase()} — their
            contribution has unknown certainty, not high certainty.
          </div>
        )}
      </div>
    </WhySection>
  );
}

export function WhyThisSession({ why }: { why?: WorkoutPrescription["why"] }) {
  if (!why) return null;

  const evidence = why.state_evidence ?? [];
  const drivers = why.state_drivers ?? [];
  const constraints = why.constraints_applied ?? [];
  const goalAlignment = why.goal_alignment?.trim() ?? "";
  const confidence = why.confidence ?? null;

  const hasConfidence =
    confidence != null &&
    (Object.keys(confidence.capacity_axes ?? {}).length > 0 ||
      confidence.weakest_capacity_axis != null ||
      (confidence.uncertainty_not_modelled ?? []).length > 0);

  if (
    evidence.length === 0 &&
    drivers.length === 0 &&
    constraints.length === 0 &&
    !goalAlignment &&
    !hasConfidence
  ) {
    return null;
  }

  return (
    <div className="rounded-[12px] border border-ac/[0.18] bg-ac/[0.05] p-[16px]">
      <div className="mb-3 flex items-center gap-2 font-mono text-[10px] font-semibold uppercase leading-none tracking-[0.1em] text-ac">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 2v6M12 22v-2M5 12H2M22 12h-3" /><circle cx="12" cy="12" r="4" /></svg>
        Why this session
      </div>
      <div className="flex flex-col gap-[14px]">
        {goalAlignment && (
          <WhySection label="Goal alignment">
            <div className="text-[12.5px] font-medium leading-[1.55] text-mute">{goalAlignment}</div>
          </WhySection>
        )}

        {evidence.length > 0 ? (
          <WhySection label="State drivers">
            <ul className="flex flex-col gap-[8px]">
              {evidence.map((ev, i) => (
                <EvidenceRow key={`${ev.axis}-${i}`} ev={ev} />
              ))}
            </ul>
          </WhySection>
        ) : (
          drivers.length > 0 && (
            <WhySection label="State drivers">
              <ul className="flex flex-col gap-[6px]">
                {drivers.map((d, i) => (
                  <li key={i} className="text-[12.5px] font-medium leading-[1.5] text-mute">{d}</li>
                ))}
              </ul>
            </WhySection>
          )
        )}

        {constraints.length > 0 && (
          <WhySection label="Constraints applied">
            <ul className="flex flex-col gap-[6px]">
              {constraints.map((c, i) => (
                <li key={i} className="text-[12.5px] font-medium leading-[1.5] text-mute">{c}</li>
              ))}
            </ul>
          </WhySection>
        )}

        {confidence != null && hasConfidence && <ConfidenceBlock confidence={confidence} />}
      </div>
    </div>
  );
}
