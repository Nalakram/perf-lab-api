// src/perflab/screens/OverviewScreen.tsx
//
// Overview is a router, and nothing else.
//
// For an AUTHENTICATED athlete this screen is real-or-explicitly-empty: every
// number comes from the backend, and anything missing renders as an empty or
// unavailable state rather than a plausible substitute (map #182, L1). A GUEST
// sees a curated, persistently-labelled preview of a sample athlete (#185, A′).
//
// The two live in separate files on purpose. Overview's five fixture leaks all
// existed because the guest path and the authenticated-degraded path were the SAME
// expression — `token ? real : sim`, `real ?? DAYS[…]` — so every "no data yet"
// state silently rendered sample-athlete numbers to a signed-in user. Splitting by
// file makes "this file cannot render a fabricated number" mechanically checkable,
// the same way TwinScreen/GuestTwinPreview did for the twin (B4).
//
// Guard rails, both blocking:
//   - overviewBoundary.test.ts  — AuthedOverview's transitive import graph must not
//                                 reach sim.ts or the guest preview.
//   - overviewModel.test.ts     — no authenticated state may yield a fabricated value.
import { useAuth } from "@/auth/useAuth";
import { AuthedOverview } from "./overview/AuthedOverview";
import { GuestOverviewPreview } from "./overview/GuestOverviewPreview";

export function OverviewScreen() {
  const { token } = useAuth();
  const isGuest = token == null;

  return (
    <section className="flex flex-col gap-[18px] px-[30px] pb-9 pt-[26px]">
      {isGuest ? <GuestOverviewPreview /> : <AuthedOverview />}
    </section>
  );
}
