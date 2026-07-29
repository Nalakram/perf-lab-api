# Browser verification gate — evidence ledger

Run date: 2026-07-29 · main @ `3e5f3d1` · fix branch `fix/overview-narrow-viewport-overflow` @ `faee58b`

## Stack under test (local target)

| component | detail |
|---|---|
| Postgres | docker `perf-lab-postgres` :5432, volume `postgres_data` (the 2026-07-28 rebuild), healthy |
| alembic head | `a038_ekf_head_correction_replay` |
| API | uvicorn from `.venv` :8000, `DATABASE_URL` + `ALLOWED_ORIGINS` exported (repo-root `.env` untouched) |
| Web | Vite :5174 (5173 taken — the documented trap; 5174 pre-added to `ALLOWED_ORIGINS`) |
| Data | `seed_all --users 5 --skip-openpl` → 5 gf athletes + 50 gym members, 655 workout logs |
| Auth | token minted via `POST /auth/token`, injected into `sessionStorage` — no password typed into a form |

Local enum baseline (identical query to the prod inventory):

```
blockgoal        Strength,Hypertrophy,Power,Hyrox,CrossFit,Running,Calisthenics,General,Recomp
blockstatus      active,completed,abandoned
macrocyclestatus active,achieved,abandoned
objectivestatus  active,achieved,abandoned
sessionstatus    pending,completed,skipped,rescheduled
weakpointsource  self_report,benchmark,inference,performance_data
```

All six match the pinned labels; `blockgoal` correctly Title-case. **This empirically
confirms the local target cannot detect prod drift** — it is clean by construction.

## Classification key

- **Observed** — reached naturally through the running app, no intervention.
- **Injected** — produced by intervention. Two distinct mechanisms, named per row:
  `fetch-patch` (in-page `window.fetch` override) and `induced-outage` (API process stopped).
  An induced outage is a real network failure, not a monkey-patch, but it is still not "in the wild".
- **Unverified** — tooling could not establish it.

## Rows

| # | Row | Result | Class | Evidence |
|---|---|---|---|---|
| 1 | Guest Overview honesty | PASS | Observed | Every fixture region badged `SAMPLE DATA`; banner "Preview — sample athlete" |
| 2 | 14-day trend labelling | PASS | Observed | Reads "FATIGUE-DERIVED TREND", not readiness — B5 child #186's resolution, visible |
| 3 | Sidebar block, guest | PASS | Observed | "Mid-base / Week 3 of 7" retained but badged `SAMPLE DATA` — PR #195 guest branch |
| 4 | Sidebar block, authed-empty | PASS | Observed | "No active block" + Create plan — PR #195 authed branch |
| 5 | `ResourceState` `screen`, guest | PASS | Observed | Objectives `:74/:77` — centred card, target icon, "Sign in to set your objectives" |
| 6 | `ResourceState` `box`, guest | PASS | Observed | Assess `:88` (implicit default). DOM-confirmed `min-h-[240px]`, `border-dashed`, `rounded-[18px]`, `p-[30px]` — border is `white/10` @0.72px, invisible in a downscaled capture |
| 7 | `ResourceState` `note`, empty | PASS | Observed | History ×5 — VO₂max, aerobic capacity, weekly load, load balance, field-test log |
| 8 | B5 Overview authority | PASS | Observed | Readiness `—` not `64`; "Readiness isn't available yet" |
| 9 | B2 `—` not fabricated `0` | PASS | Observed | Twin snapshot all four metrics `—` + "No twin state yet" |
| 10 | B5 habit 6th leak | PASS | Observed | "No streak yet", adherence `—`, no bar drawn |
| 11 | B5 check-in auto-prompt deleted | PASS | Observed | No modal fired on authed load (#191) |
| 12 | No fixtures on authed path | PASS | Observed | Zero `SAMPLE DATA` badges anywhere when signed in |
| 13 | B1 History literals gone | PASS | Observed | No `64` / `58.4` / `320`; real wellness (HRV 67–74ms), `—` for missing sleep/mood |
| 14 | B1 range-aware empty copy | PASS | Observed | Verbatim match to `HistoryScreen.tsx:421` and `:465` |
| 15 | B1 range toggle is live | PASS | Observed | Clicking All moved selection; subtitle "last 12 weeks" → "last 52 weeks" |
| 16 | `ResourceState` `screen`, error | PASS | Injected · fetch-patch | Objectives: custom title "Couldn't load your objectives" + Retry. Neutral card chrome — `screen` has no error-tone branch (`ResourceState.tsx:203-217`), consistent with source |
| 17 | B3.2 failed fetch ≠ empty state | PASS | Injected · fetch-patch | Failure notice renders, **not** "Set your first objective" |
| 18 | `ResourceState` `box`, error | PASS | Injected · induced-outage | Assess: default title "Couldn't load this" (`:108`), body from `branch.error.message`, no action |
| 19 | **Refresh-error retention / stale** | PASS | Injected · induced-outage | Banner "Couldn't refresh your assessment surface — showing your last loaded benchmarks" (exact custom `staleLabel`) **over a fully retained, still-usable catalog** — did not blank to an error box. Confirms `isStale` = success + failed refresh |
| 20 | Narrow viewport (390px) | **FAIL → FIXED → PASS** | Injected · iframe viewport | See finding below |
| 21 | Wide viewport (2752px) | PASS | Observed | No overflow; ring + session block still side by side after the fix |
| 22 | Loading branch renders, all 3 variants | PASS | Observed | MutationObserver caught 8 renders / 6 distinct copies on natural mount — `box` "Loading your assessment surface…", `note` ×4 ("Loading history…", "Loading field tests…", "Loading recent samples…", "Loading training load…"), `screen` "Loading your objectives… / Fetching what your plan is pointed at." All `role="status" aria-live="polite"`. An observer records; it does not intervene |
| 23 | `note` variant, error branch | PASS | Injected · induced-outage | All 6 History sites render custom `error.body` in error tone — readiness, VO₂max, aerobic, wellness, training load, field-test log. No card fabricated data under failure |
| 24 | Initial-load flash, controlled | see §Latency | Injected · latency shim | Run separately under a deliberate delay — absence of observation is not evidence of absence |
| 25 | Long-text placement | **Unverified** | — | Deliberately not driven — low yield, and the gate is not an open-ended visual QA program |
| 26 | B3.2 Settings goal chips stay lit | **Unverified** | — | Deliberately not driven, as above |
| 27 | Twin guest arm returns null | **Unverified** | — | Deliberately not driven, as above |

## Finding — horizontal overflow at phone width (fixed)

At a genuine 390px viewport the authed Overview scrolled sideways by 189px
(`scrollWidth` 564 vs `clientWidth` 375). Two independent causes, each one level
below where responsiveness had already been handled:

1. `AuthedOverview.tsx:143` — `flex items-start gap-6` with a `w-[300px] flex-none`
   child and no wrap. The parent grid at `:141` already collapses via
   `lg:grid-cols-[1fr_320px]`; this inner row was missed.
2. `overviewLeaves.tsx:80` — header `justify-between`, no wrap; title + Check in /
   Log workout could not fit.

Fixed on `fix/overview-narrow-viewport-overflow` @ `faee58b`. Re-ran the row:
overflow 0. Nothing hidden to achieve it. `npm run verify` green — tsc -b,
15/15 test files, 216 tests, production build — including both honesty guards.

## Method notes worth keeping

- **`resize_window` is confirmed useless for responsive work.** It reports success but
  `window.innerWidth` and every `matchMedia` result are unchanged. The prior session's
  dead-end was right; this run verified it via `matchMedia` rather than screenshot size.
- **A same-origin iframe *does* give a real viewport** — `innerWidth` 390,
  `(max-width:768px)` matches. This is the working method for responsive rows.
- Screenshots are downscaled: real CSS viewport 2752px, capture 1564px (DPR 1.40).
  Never judge hairline borders or overflow from a capture — query the DOM.
- **`javascript_tool` blocks the *output* of scripts that override `fetch`, but still
  executes them.** The patch was live while the tool reported `[BLOCKED]`. Discriminate
  by error text: the patch appends `[gate-injected]`, a genuine outage does not.
- The **"Preview empty state" toggle is not a `ResourceState` affordance.** It swaps the
  whole main region for `AppShell`'s `EmptyState` (`AppShell.tsx:63`) and is gated off on
  assess/onboarding/settings. Using it to claim "empty branch observed" would be wrong.
- No seeder creates `AthleteState` — confirmed. Only the previous gate session's two
  hand-driven accounts have snapshots. Seeded athletes give a "logs but no state" fixture.

## Disproven hypothesis (recorded so it is not re-raised)

`load 0` on every Recent Activity row looked like a fabricated zero of exactly the class
B2 removed. It is not. `total_volume_load` is genuinely `0` in all 182 rows (zero nulls) —
the seeder writes 0 for cardio, which is correct — and `WorkoutLogSummary`
(`types.gen.ts:3237`, matching `app/schemas/history.py:24`) types it non-nullable, so the
unguarded `Math.round` at `AuthedOverview.tsx:499` cannot receive null per contract. The
nullable declaration at `types.gen.ts:3206` belongs to the *write* schema. No defect.
