// src/perflab/screens/twin/viewingLabel.ts
//
// Date labels for the Digital Twin's time-travel scrub. Both twin bodies render
// the same "18 Jun · Yesterday" shape, but from different inputs: the live body
// scrubs recorded snapshots keyed by ISO timestamp, the guest preview scrubs a
// fixed sample window already holding Date objects. They shared a module-local
// MONTHS table while they lived in one file; this keeps that table single-source
// now that they don't.
//
// Pure module: no React, no fetching, so it is unit-testable through its
// interface.

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "18 Jun" — day-of-month plus abbreviated month, the twin's compact date form. */
export function dayMonthLabel(d: Date): string {
  return `${d.getDate()} ${MONTHS[d.getMonth()]}`;
}

/**
 * "Viewing" date + relative word from a recorded snapshot's timestamp.
 * An unparseable timestamp is echoed back verbatim with no relative word —
 * never silently rendered as today.
 */
export function viewingLabel(iso: string): { date: string; when: string } {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return { date: iso, when: "" };
  const date = dayMonthLabel(d);
  const a = new Date();
  a.setHours(0, 0, 0, 0);
  const b = new Date(d);
  b.setHours(0, 0, 0, 0);
  const days = Math.round((a.getTime() - b.getTime()) / 864e5);
  const when = days <= 0 ? "Today" : days === 1 ? "Yesterday" : `${days} days ago`;
  return { date, when };
}
