// src/perflab/screens/overview/overviewClock.ts
//
// Wall-clock display helpers for the Overview header. Separate from
// ./overviewLeaves so that file exports components only (react-refresh).
//
// These read the VIEWER's device clock and describe the device — they are not a
// claim about the athlete's training day. The canonical athlete day is
// backend-owned and does not exist yet (#191), so nothing may key off these:
// no check-in eligibility, no "logged today", no cache key. Display only.
// `now` is injectable so the behaviour is testable without freezing time.

/** Time-of-day greeting prefix from the viewer's wall clock. */
export function greetingPrefix(now: Date = new Date()): string {
  const h = now.getHours();
  if (h < 12) return "Good morning";
  if (h < 18) return "Good afternoon";
  return "Good evening";
}

/** "Saturday · 4 Jul" from the viewer's wall clock. */
export function dateLine(now: Date = new Date()): string {
  const weekday = now.toLocaleDateString(undefined, { weekday: "long" });
  const month = now.toLocaleDateString(undefined, { month: "short" });
  return `${weekday} · ${now.getDate()} ${month}`;
}
