---
task_id: TASK-templates
from: coder
to: orchestrator
timestamp: 2026-08-26 19:05
turn: 1
cycle: 1
status: ready
---

## Task Implemented
Add session templates to the thin domains in `app/logic/candidate_library.py` — no domain left at effective pool depth 1, thinnest domains given real alternatives, priority: general > gymnastics > sprinting > hypertrophy/power/calisthenics/grip.

Note on process: no handoff file existed in `agent_collab/handoffs/claimed/` and no matching entry in `task_state.json` for this task — the full task spec was given directly in the launch prompt (touch only `app/logic/candidate_library.py`, branch `feat/catalog-and-template-expansion` already checked out, no commit/push). I proceeded on that basis since the instructions were unambiguous and in-scope; I did not create or edit anything under `agent_collab/` per my restrictions.

## Files Changed
- `app/logic/candidate_library.py` — added 9 new `CandidateTemplate` entries across 7 lists (pure addition, 237 insertions, 0 deletions, 0 lines touched elsewhere in the file).

No other file was edited. `app/data/exercise_bulk.py` and `tests/test_prescribed_exercise_names_resolve.py` show as modified in `git status` but that is a concurrent agent's work (confirmed — I read but never wrote either file).

## Templates added

| branch_id | domain | duration_min | slots |
|---|---|---|---|
| `gpp_strength_foundation` | general | 50 | 3 |
| `gpp_conditioning` | general | 40 | 3 |
| `gpp_mobility` | general | 30 | 3 |
| `gym_strength` | gymnastics | 55 | 3 |
| `run_speed_endurance` | running (SPRINTING_TEMPLATES pool) | 40 | 2 |
| `hyp_upper_split` | hypertrophy | 60 | 3 |
| `power_reactive` | power | 40 | 3 |
| `cal_conditioning` | calisthenics | 35 | 3 |
| `grip_crush_pinch` | grip | 30 | 3 |

9 templates, 26 exercise_slots total. Every new template has its own `exercise_slots` (none fall to the equipment map) and its own `ScoringSpec` (none inherit a sibling branch's scoring via the `_DOMAIN_SCORERS` catch-all).

## Effective pool depth per domain (pairs collapsed)

| domain | before | after |
|---|---|---|
| general | 1 | 4 |
| gymnastics | 1 | 2 |
| sprinting (SPRINTING_TEMPLATES) | 1 | 2 |
| hypertrophy | 2 | 3 |
| power | 2 | 3 |
| calisthenics | 2 | 3 |
| grip | 2 | 3 |
| strength / running / mixed / powerlifting / weightlifting | unchanged | unchanged (out of scope) |

No domain sits at 1 anymore.

## Slot-resolution proof (live catalog, re-run at report time)

Catalog built from `EXERCISES + bulk_exercises()`, 203 unique names at verification time. Ran `resolve_slots` directly (no prescriber involved) for every new slot:

```
=== hypertrophy :: hyp_upper_split (60 min, 3 slots) ===
  slot 0: pattern=push_horizontal, load=barbell                       -> Bench Press
  slot 1: pattern=pull_horizontal, load=barbell                       -> Barbell Row
  slot 2: pattern=push_vertical, modality=Hypertrophy, load=dumbbell  -> Dumbbell Shoulder Press

=== power :: power_reactive (40 min, 3 slots) ===
  slot 0: pattern=jump, domain=running                                -> Broad Jump
  slot 1: pattern=jump, domain=running                                -> Seated Box Jump
  slot 2: pattern=core, max_skill=0.45                                -> Russian Twist

=== sprinting (SPRINTING_TEMPLATES) :: run_speed_endurance (40 min, 2 slots) ===
  slot 0: pattern=run, modality=Power, domain=running                 -> Bounding Drill
  slot 1: pattern=run, modality=Running                                -> 400m Intervals

=== gymnastics :: gym_strength (55 min, 3 slots) ===
  slot 0: pattern=pull_vertical, modality=Calisthenics, domain=gymnastics -> Chest-to-Bar Pull-Up
  slot 1: pattern=push_vertical, modality=Calisthenics, domain=gymnastics -> Ring Dip (Weighted)
  slot 2: pattern=core, modality=Calisthenics, domain=gymnastics          -> Strict Toes-to-Bar

=== calisthenics :: cal_conditioning (35 min, 3 slots) ===
  slot 0: pattern=push_horizontal, modality=Calisthenics, load=bodyweight, max_skill=0.4 -> Push-up
  slot 1: pattern=pull_vertical, modality=Calisthenics, load=bodyweight, max_skill=0.5   -> Pull-up
  slot 2: pattern=single_leg, load=bodyweight, max_skill=0.45                            -> Step-Up

=== grip :: grip_crush_pinch (30 min, 3 slots) ===
  slot 0: pattern=pull_vertical, modality=Strength, domain=grip        -> Captains of Crush Gripper
  slot 1: pattern=carry, domain=grip                                   -> Bottom-Up Plate Pinch Hold
  slot 2: pattern=hinge, load=barbell                                  -> Fat Bar Deadlift

=== general :: gpp_strength_foundation (50 min, 3 slots) ===
  slot 0: pattern=squat, modality=Strength, load=barbell               -> Back Squat
  slot 1: pattern=hinge, load=barbell                                  -> Romanian Deadlift
  slot 2: pattern=push_horizontal, modality=Strength, load=barbell     -> Bench Press

=== general :: gpp_conditioning (40 min, 3 slots) ===
  slot 0: pattern=bike, modality=Conditioning                          -> Assault Bike
  slot 1: pattern=row, modality=Conditioning                           -> SkiErg
  slot 2: pattern=core, modality=Strength, max_skill=0.35              -> Plank

=== general :: gpp_mobility (30 min, 3 slots) ===
  slot 0: pattern=single_leg, max_skill=0.5                            -> Lateral Lunge
  slot 1: pattern=core, max_skill=0.35                                 -> 90/90 Hip Switch
  slot 2: pattern=single_leg, max_skill=0.3                            -> Calf Raise
```

All 26 slots resolved to a real, distinct-per-slot movement. None unresolved. Re-ran identically against the catalog both before and after the concurrent catalog agent's edits landed (181 rows -> 203 rows) — same 26 resolutions both times, since no new slot depends on any row the concurrent agent might add.

## Branch_id uniqueness (whole library, live re-check)
```
duplicate branch_ids across GOAL_TEMPLATE_LIBRARY: {'gym_skill': 2}
total templates in dict: 37
```
Only the pre-existing `gym_skill` duplicate (STRENGTH... actually GYMNASTICS_TEMPLATES vs CALISTHENICS_TEMPLATES, both domain-tagged differently) remains, as instructed — left untouched. No new collisions among the 9 added templates or against any existing one.

## Acceptance Criteria Self-Check
- [x] No domain left at effective pool 1 — see depth table above; `app/logic/candidate_library.py:632-654` (`GOAL_TEMPLATE_LIBRARY`) plus `SPRINTING_TEMPLATES`.
- [x] `general` deepened highest priority, 1 -> 4 templates.
- [x] `gymnastics` deepened, 1 -> 2.
- [x] `sprinting` (`SPRINTING_TEMPLATES`) deepened, 1 -> 2; did not touch the unreachable-routing bug at `:661-662`/`:641` (out of scope, left alone).
- [x] `hypertrophy`, `power`, `calisthenics`, `grip` each deepened from 2 -> 3.
- [x] Every new template has non-empty `exercise_slots`.
- [x] Every new template has its own `ScoringSpec` — no reliance on `_DOMAIN_SCORERS` catch-all inheritance.
- [x] Tags used only from the recognized `_weak_point_coverage` vocabulary where genuinely applicable (`aerobic_base`, `hip_hinge`, `squat_pattern`, `grip`, `hip_mobility`, `ankle_mobility`, `gymnastics_skill`, `overhead_stability`); left `tags=[]` rather than stuffing where nothing in the vocabulary fit (e.g. `hyp_upper_split`, `power_reactive`, `run_speed_endurance`, `cal_conditioning`).
- [x] `focus` kept honest against the declared slots (rewrote each `focus` string to name the pattern the slots will actually resolve to, verified against the resolution proof above).
- [x] `skill_target` set deliberately on main-lift / main-skill slots (e.g. `gpp_strength_foundation` squat `skill_target=0.70` -> Back Squat, matching the documented canonical example; gymnastics push_vertical `skill_target=0.82` -> Ring Dip (Weighted), not the simplest push_vertical movement).
- [x] Pinned test 1 (`tests/test_prescriber_session_prefs.py:29-30`, `pl_sbd_main`) untouched — I did not add to `powerlifting`.
- [x] Pinned test 2 (`tests/test_prescriber_exercise_selection.py:100-120`, `hyp_maintenance` must still win Hypertrophy at `muscular=70.0`) protected structurally: the one new hypertrophy template (`hyp_upper_split`) carries `state_eligible=lambda s: s.fatigue_f.muscular < 55.0` (`candidate_library.py`, in `HYPERTROPHY_TEMPLATES`), so it is not even in the eligible pool at `muscular=70.0` — no scoring race to win or lose.

## Test Results
```
$ .venv/Scripts/python.exe -m pytest tests/test_prescriber_candidates.py tests/test_prescriber_exercise_selection.py tests/test_prescriber_session_prefs.py tests/test_candidate_library_scoring.py tests/test_candidate_scoring_guardrails.py tests/test_prescriber_safety.py -q
........................................................................ [ 56%]
........................................................                 [100%]
128 passed in 0.36s

$ .venv/Scripts/python.exe -m ruff check app/logic/candidate_library.py
All checks passed!

$ .venv/Scripts/python.exe -m pyright app/logic/candidate_library.py
0 errors, 0 warnings, 0 informations
```

Also spot-checked the two other test files that reference `candidate_library`/template lists (`tests/test_derived_metric_missing_inputs.py`, `tests/test_tissue_risk_model_not_live_wired.py`, both unrelated to the specific gate list but touching the same module) — `9 passed`.

## Templates dropped
None. All 9 planned templates were kept; the one collision risk (`hyp_upper_split` vs `hyp_maintenance` at `muscular=70.0`) was resolved by gating eligibility rather than dropping the template or tuning its score to lose a race — cleaner and unambiguous, and it still leaves `hyp_upper_split` free to win under fresher states, which is the point of adding it.

## Known Gaps / Notes for Critic
- No new dependencies.
- `hyp_upper_split`'s `state_eligible` (muscular fatigue < 55) means it is simply invisible above that threshold rather than losing on score — worth the Critic double-checking this reads as intentional design (matches existing precedent: `strength_skill_acq` gates on skill_state, `strength_variety` gates on habit_strength) rather than a dodge.
- `run_speed_endurance` lives in `SPRINTING_TEMPLATES`, which per the task brief is reachable only via the special case at `candidate_library.py:661-662` (`domain == "running" and goal == "Sprinting"`) — the `GOAL_TEMPLATE_LIBRARY["sprinting"]` key itself remains unreachable, pre-existing and explicitly out of scope per the handoff.
- The catalog agent(s) working concurrently on `app/data/exercise_bulk.py` changed the catalog from 181 to 203 rows partway through this task; slot resolution was re-verified against the live 203-row catalog at report time and no new slot depends on any row added after I started, so no rework is needed if the catalog grows further before this lands.
