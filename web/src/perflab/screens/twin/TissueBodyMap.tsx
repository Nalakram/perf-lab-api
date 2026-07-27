// src/perflab/screens/twin/TissueBodyMap.tsx
//
// The tissue body-map: mannequin SVG + per-region value list + legend.
//
// This markup used to exist twice — once for the live authed twin and once
// inlined in the guest sim preview — and the two copies had converged to a
// 34-of-36-line verbatim match. The only real differences were WHERE the number
// came from and WHETHER a region row was clickable, so those are the only two
// things this component takes as props.
//
// Deliberately presentational: no resource types, no fetching, no fixture data.
// The live path and the labelled-sample path can therefore share one renderer
// without the sample path leaking into the live one — the caller supplies the
// values and stays responsible for their honesty.
//
// (COLORS / fatigueColor / swatch / TISSUE_ORDER come from sim.ts, which is also
// the app's de-facto palette + ordering module; those exports carry no fixture
// data and are already used on live authed paths.)

import { COLORS, fatigueColor, swatch, swatchLite, TISSUE_ORDER } from "../../sim";

/** Region labels are spelled as in TISSUE_ORDER: "Knee", "Lumbar", "Hip", … */
export interface TissueBodyMapProps {
  /** Resolved 0–100 load for a region label. The caller owns missing-value policy. */
  getT: (label: string) => number;
  /**
   * When supplied, region rows become clickable and get the pointer cursor.
   * Omitted on the live path, where there is nothing to open.
   */
  onRegionClick?: (label: string) => void;
}

export function TissueBodyMap({ getT, onRegionClick }: TissueBodyMapProps) {
  const reg = (label: string) => {
    const c = fatigueColor(getT(label));
    return { fill: swatch(c), stroke: c };
  };
  const tm = {
    knee: reg("Knee"),
    lumbar: reg("Lumbar"),
    hip: reg("Hip"),
    ankle: reg("Ankle"),
    shoulder: reg("Shoulder"),
    elbow: reg("Elbow"),
    wrist: reg("Wrist"),
    finger: reg("Finger"),
  };
  const tHalo = swatchLite(fatigueColor(getT("Knee")));
  return (
    <>
      <div className="grid grid-cols-[150px_1fr] items-center gap-[18px]">
        <svg viewBox="0 0 130 300" className="block h-auto w-full">
          <g fill="#1b212b" stroke="rgba(255,255,255,.06)" strokeWidth="1">
            <circle cx="65" cy="24" r="14" /><rect x="47" y="42" width="36" height="70" rx="15" /><rect x="28" y="46" width="13" height="74" rx="6.5" /><rect x="89" y="46" width="13" height="74" rx="6.5" /><rect x="45" y="104" width="40" height="26" rx="13" /><rect x="49" y="126" width="14" height="96" rx="7" /><rect x="67" y="126" width="14" height="96" rx="7" />
          </g>
          <circle cx="56" cy="172" r="12" fill={tHalo} className="animate-pl-pulse" /><circle cx="74" cy="172" r="12" fill={tHalo} className="animate-pl-pulse" />
          <g strokeWidth="1.5">
            <circle cx="40" cy="54" r="5.5" fill={tm.shoulder.fill} stroke={tm.shoulder.stroke} /><circle cx="90" cy="54" r="5.5" fill={tm.shoulder.fill} stroke={tm.shoulder.stroke} />
            <circle cx="34" cy="86" r="5.5" fill={tm.elbow.fill} stroke={tm.elbow.stroke} /><circle cx="96" cy="86" r="5.5" fill={tm.elbow.fill} stroke={tm.elbow.stroke} />
            <circle cx="34" cy="114" r="5.5" fill={tm.wrist.fill} stroke={tm.wrist.stroke} /><circle cx="96" cy="114" r="5.5" fill={tm.wrist.fill} stroke={tm.wrist.stroke} />
            <circle cx="34" cy="127" r="4" fill={tm.finger.fill} stroke={tm.finger.stroke} /><circle cx="96" cy="127" r="4" fill={tm.finger.fill} stroke={tm.finger.stroke} />
            <circle cx="65" cy="98" r="6" fill={tm.lumbar.fill} stroke={tm.lumbar.stroke} />
            <circle cx="54" cy="116" r="5.5" fill={tm.hip.fill} stroke={tm.hip.stroke} /><circle cx="76" cy="116" r="5.5" fill={tm.hip.fill} stroke={tm.hip.stroke} />
            <circle cx="56" cy="172" r="6.5" fill={tm.knee.fill} stroke={tm.knee.stroke} /><circle cx="74" cy="172" r="6.5" fill={tm.knee.fill} stroke={tm.knee.stroke} />
            <circle cx="56" cy="214" r="5.5" fill={tm.ankle.fill} stroke={tm.ankle.stroke} /><circle cx="74" cy="214" r="5.5" fill={tm.ankle.fill} stroke={tm.ankle.stroke} />
          </g>
        </svg>
        <div className="flex flex-col gap-[9px]">
          {TISSUE_ORDER.map((k) => {
            const v = getT(k);
            const c = fatigueColor(v);
            return (
              <div
                key={k}
                onClick={onRegionClick ? () => onRegionClick(k) : undefined}
                className={onRegionClick ? "flex cursor-pointer items-center gap-[9px]" : "flex items-center gap-[9px]"}
              >
                <span className="h-[7px] w-[7px] flex-none rounded-[2px]" style={{ background: c }} />
                <span className="flex-1 text-[12px] font-medium leading-none" style={{ color: v >= 45 ? COLORS.soft : COLORS.mute }}>{k}</span>
                <span className="font-mono text-[12px] font-semibold leading-none" style={{ color: v >= 45 ? c : COLORS.soft }}>{v}</span>
              </div>
            );
          })}
        </div>
      </div>
      <div className="mt-4 flex gap-4 border-t border-white/[0.06] pt-[14px] text-[11px] font-medium leading-none text-mute">
        <span><span className="mr-[6px] inline-block h-[8px] w-[8px] rounded-[2px] bg-good" />ready</span>
        <span><span className="mr-[6px] inline-block h-[8px] w-[8px] rounded-[2px] bg-warn" />monitor</span>
        <span><span className="mr-[6px] inline-block h-[8px] w-[8px] rounded-[2px] bg-hot" />load high</span>
      </div>
    </>
  );
}
