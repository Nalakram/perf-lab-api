---
task_id: TASK-009
from: coder
to: orchestrator
timestamp: 2026-08-26 18:21
turn: 1
cycle: 1
status: ready
---

## Task Implemented
TASK-009 — catalog-and-template-expansion: close the 7 known prescriber/catalog naming gaps and deepen thin movement-pattern coverage (`pull_horizontal`, `single_leg`, `carry`, `core`/rotation, `push_vertical`).

## Files Changed
- `app/data/exercise_bulk.py` — added a `gap_fill` block (7 rows, one per `KNOWN_CATALOG_GAPS` entry, exact-string matches) plus five pattern-breadth blocks (`pull_horizontal_extra`, `single_leg_extra`, `carry_extra`, `core_rotation_extra`, `push_vertical_extra`, 3 rows each = 15) appended at the end of `bulk_exercises()`. 22 new rows total.
- `tests/test_prescribed_exercise_names_resolve.py` — emptied `KNOWN_CATALOG_GAPS` (was 7 entries at :39-49, now `frozenset()`) since all 7 gaps now have catalog rows. No other line in this file touched.

## Acceptance Criteria Self-Check
- [x] Part 1, all 7 gap rows added with exact name strings, honoring the "not a substitute" distinction called out in each removed comment — `app/data/exercise_bulk.py` gap_fill block (end of file, before the return): `Chest-Supported Row` (dumbbell, distinct from Barbell/Dumbbell/Cable Row), `DB Floor Press` (dumbbell load_type, vs. the existing barbell `Floor Press`), `DB RDL` (bilateral dumbbell hinge, distinct from `Single-Leg RDL`), `Dips` (bodyweight, skill 0.4 vs. `Ring Dip`'s 0.7 — deliberately easier/more stable), `Hanging Knee Raise` (dynamic, skill 0.3 vs. `Hanging L-Sit`'s isometric 0.72), `Hanging Leg Raise` (dynamic, skill 0.45, harder than the knee-raise variant but still dynamic not isometric), `Split Squat` (dumbbell, unilateral=True, skill 0.4 vs. `Bulgarian Split Squat`'s rear-foot-elevated 0.5).
- [x] `KNOWN_CATALOG_GAPS` entries deleted after adding each row — `tests/test_prescribed_exercise_names_resolve.py:39`.
- [x] Part 2, 15 new rows (within the 12-18 range) deepening the five named-thin patterns — `pull_horizontal_extra` (Seal Row, Meadows Row, Chest-Supported T-Bar Row), `single_leg_extra` (Reverse Lunge, Lateral Lunge, Single-Leg Box Squat), `carry_extra` (Single-Arm Farmer Carry, Overhead Kettlebell Carry, Zercher Carry), `core_rotation_extra` (Cable Woodchop, Landmine Rotation, Russian Twist), `push_vertical_extra` (Landmine Press, Seated Dumbbell Shoulder Press, Bottoms-Up Kettlebell Press) — all in `app/data/exercise_bulk.py`.
- [x] Row contract followed — `_row` 10-positional + keyword-optional, `_BaseRow`/`_VariantRow` typed lists matching neighboring blocks' idiom exactly.
- [x] Only legal (already-in-use) categorical values used — verified via the two enumeration commands the task specified, no new equipment/tag/sport_domain strings introduced (checked `obliques` was NOT already in use and deliberately avoided it, using `core` instead — see Notes).
- [x] No `e1rm_benchmark_code` set on any new row.
- [x] No name collisions — verified both within the new 22 names and against the full `EXERCISES + bulk_exercises()` set (203 unique names, 203 total).
- [x] No migration added/touched; `app/scripts/seed_exercises.py` untouched.

## Test Results
```
$ .venv/Scripts/python.exe -c "from app.data.exercise_bulk import bulk_exercises; rows=bulk_exercises(); print(len(rows)); assert len({r['name'] for r in rows})==len(rows), 'dup name'"
bulk rows: 147
no dup in bulk: OK

$ .venv/Scripts/python.exe -c "... EXERCISES+bulk_exercises() dedup check ..."
total: 203 unique: 203
cross-file: OK

$ .venv/Scripts/python.exe -m pytest tests/test_prescribed_exercise_names_resolve.py -v
tests/test_prescribed_exercise_names_resolve.py::test_every_prescribable_exercise_name_resolves PASSED
tests/test_prescribed_exercise_names_resolve.py::test_known_gaps_are_actually_still_missing PASSED
tests/test_prescribed_exercise_names_resolve.py::test_known_gaps_are_all_actually_referenced PASSED
tests/test_prescribed_exercise_names_resolve.py::test_the_catalog_is_reachable_at_all PASSED
4 passed in 0.20s

$ .venv/Scripts/python.exe -m ruff check app/data/exercise_bulk.py tests/test_prescribed_exercise_names_resolve.py
All checks passed!

$ .venv/Scripts/python.exe -m pyright app/data/exercise_bulk.py
0 errors, 0 warnings, 0 informations
```

Movement-pattern distribution, `EXERCISES + bulk_exercises()`, before vs after:
```
BEFORE (203 - 22 = 181 rows):
hinge 30, squat 20, pull_vertical 17, mixed 17, push_horizontal 14, push_vertical 14,
run 13, carry 12, core 12, single_leg 11, pull_horizontal 8, jump 7, row 4, bike 2

AFTER (203 rows):
hinge 31, squat 20, push_vertical 17, pull_vertical 17, core 17, mixed 17,
push_horizontal 16, single_leg 15, carry 15, run 13, pull_horizontal 12, jump 7, row 4, bike 2
```
pull_horizontal +4 (8→12), single_leg +4 (11→15), carry +3 (12→15), core +5 (12→17), push_vertical +3 (14→17). push_horizontal grew +2 incidentally (two of the seven gap rows — `DB Floor Press`, `Dips` — land there since that's their real pattern, not a judgment call to pad that bucket).

## Known Gaps / Notes for Critic
- **`pyright` on the test file is not clean, but this predates my change.** I ran `python -m pyright tests/test_prescribed_exercise_names_resolve.py` both before (via `git stash`) and after my edit: identical 5 errors both times (`reportUnhashable`/`reportReturnType` on `_catalog_names`, three `reportPrivateUsage` on the prescriber internals), just shifted up by exactly 10 lines (the size of the block I deleted). My only diff to that file is the single `KNOWN_CATALOG_GAPS` line. The task's pyright gate only named `app/data/exercise_bulk.py`, which is clean — flagging this so it isn't mistaken for a regression.
- **Judgment calls a reviewer may want to second-guess:**
  - `Dips` uses `equipment_required: ["parallettes"]` — there's no "dip bars"/"parallel bars" equipment string in the catalog's existing vocabulary, and `parallettes` (used elsewhere for L-Sit Hold) was the closest existing value rather than inventing a new one or leaving it bodyweight-only.
  - `Split Squat` set `unilateral=True` for consistency with the closest existing analogs (`Walking Lunge`, `Skater Squat`), though I noticed the existing catalog is inconsistent here — `Pistol Squat`/`Shrimp Squat`/`Cossack Squat` are `single_leg` pattern but don't set `unilateral=True`. I didn't touch those (out of scope) but a reviewer may want a follow-up task to backfill that flag consistently.
  - Rotation rows (`Cable Woodchop`, `Landmine Rotation`, `Russian Twist`) use `primary_muscles: ["core"]` rather than introducing `"obliques"` — verified that string is not used anywhere in the existing catalog (`EXERCISES + bulk_exercises()`), so I stuck to the established vocabulary instead of adding a new muscle term.
  - `skill_demand`/`impact_level` values were set relative to the closest comparable existing row in each case (e.g., `Chest-Supported Row` at 0.25/0.25, slightly below plain `Dumbbell Row`'s 0.3/0.3, since chest support removes lumbar stabilization demand) — these are my calibration judgment, not derived from any spec.
- No new dependencies introduced. Did not touch `app/logic/candidate_library.py` (owned by a concurrent agent) or `app/scripts/seed_exercises.py`.
