---
task_id: TASK-009
from: coder
to: orchestrator
timestamp: 2026-08-26 18:37
turn: 2
cycle: 1
status: ready
---

## Task Implemented
TASK-009 (continuation) — catalog-and-template-expansion: close movement-vocabulary gaps against the 141 Evox CrossFit movements (`https://www.getevox.fit/standards/movements`, scraped 2026-08-26), prioritizing ENDURANCE → GYMNASTICS → OLYMPIC → CARDIO → STRENGTH/uncategorized.

## Files Changed
- `app/data/exercise_bulk.py` — appended 5 new named blocks (`endurance_vocab`, `gymnastics_vocab`, `olympic_vocab`, `cardio_vocab`, `strength_vocab`) at the end of `bulk_exercises()`, 59 new rows total (206 bulk rows, up from 147).

No other file touched. Did not touch `app/logic/candidate_library.py` (owned by a concurrent agent).

## Rows added by category (59 total)
- **ENDURANCE (3):** Bike Erg, Swim, Sprint
- **GYMNASTICS (15):** Air Squat, Butterfly Pull-up, Kipping Pull-up, L-sit Pull-up, Deficit Handstand Push-up, Kipping Handstand Push-up, Handstand Walk, Legless Rope Climb, Ring Row, Knees to Elbow, V-up, Parallette Hold, Weighted Dip, Diamond Push-up, Hand Release Push-up
- **OLYMPIC (12):** American Kettlebell Swing, Russian Kettlebell Swing, Cluster, Dumbbell Clean & Jerk, Dumbbell Hang Clean, Ground-to-Overhead, Hang Power Snatch, Jerk, Kettlebell Clean, Medicine Ball Clean, Squat Clean, Thruster
- **CARDIO (18):** Abmat Sit-up, Sit-up, Bar Facing Burpee, Burpee Box Jump Over, Burpee Broad Jump, Burpee Pull-up, Box Jump Over, Crossover, Dumbbell Box Step Over, High Knees, Jumping Jack, Jumping Lunges, Lateral Burpee, Med-Ball Box Step-Over, Mountain Climber, Shuttle Run, Single Under, Triple Under
- **STRENGTH/uncategorized (11):** Dumbbell Deadlift, Dumbbell Front Rack Lunge, Dumbbell Overhead Lunge, Dumbbell Shoulder to Overhead, Lunges, Lunges (Barbell), Overhead Squat, Pendlay Row, Sandbag Lunges, Sumo Deadlift High Pull, Wall Sit

## Every Evox movement SKIPPED as an existing duplicate (movement identity, not string match)
32 of the 141 Evox movements were skipped. 50 more were caught by a normalized-string exact match (plurals/case aside, e.g. `Back Squat`, `Bench Press`, `Pull-up`, `Push-up`, `Overhead Press`... — trivial, not listed here). The 32 below required judgment (fuzzy match would have missed most of these, or over-flagged false positives):

| Evox name | Existing catalog name it maps to | Why same movement |
|---|---|---|
| Deadlift | Conventional Deadlift | per repo-owner correction — catalog is more specific |
| Strict Press | Overhead Press | catalog's barbell OHP is inherently strict |
| Strict Pull-up | Pull-up | existing row's coaching note ("full hang to chin over bar") already describes strict form; its skill_demand 0.5 matches the task's own calibration anchor for `Pull-up` |
| Strict Handstand Push-up | Handstand Push-up | existing skill_demand 0.9 already reflects the un-assisted strict variant |
| Strict Ring Dip | Ring Dip | ring dips are strict by default; no kip qualifier on the existing row |
| Dip | Dips | same bodyweight dip added by the prior agent |
| Bent Over Row | Barbell Row | identical movement, existing row's own name is generic |
| Bike (Assault/Echo) | Assault Bike | same fan-bike equipment/movement |
| Box Step-up | Step-Up | Evox itself lists this twice (`Box Step-up` and `Step-up`); both map to the one existing row |
| Row | Rowing (Ergometer) | same erg movement |
| Run | Easy Run | generic continuous run = the existing beginner-pace run |
| Clean | Squat Clean (newly added) | Evox lists `Clean` and `Squat Clean` at identical category/difficulty (Oa/Oa) — redundant naming on Evox's side; added the more specific term, per the `Deadlift`→`Conventional Deadlift` precedent |
| Clean & Jerk | Clean and Jerk | `&` vs `and`, same benchmark lift |
| Snatch | Snatch (Full) | generic full/squat-catch snatch |
| Squat Snatch | Snatch (Full) | squat catch is what "full snatch" means — same lift as generic `Snatch` |
| Hang Clean | Hang Clean (Full) | matches the existing Hang Power Clean / Hang Clean (Full) distinction Evox itself draws |
| Kettlebell Clean & Press | Kettlebell Clean and Press | `&` vs `and` |
| Kettlebell Thruster | Kettlebell Goblet Squat to Press | same squat+press-overhead movement with a kettlebell, existing row's name is just more descriptive |
| Dumbbell Snatch | Alternating DB Snatch | a DB snatch is inherently single-arm/alternating |
| Single Arm Dumbbell Snatch | Alternating DB Snatch | same as above — Evox's own two names for one movement |
| Dumbbell Walking Lunge | Walking Lunge | existing row already uses dumbbell load_type |
| Walking Lunges | Walking Lunge | plural, same movement |
| Farmers Carry | Farmer Carry | pluralization only |
| Farmers Walk | Farmer Carry | carry vs walk, same loaded-carry movement |
| Yoke Carry | Yoke Walk | carry vs walk, same strongman event |
| Hollow Hold | Hollow Body Hold | shortened name, same isometric hold |
| Plank Hold | Plank | "Hold" suffix only |
| L-sit | L-Sit Hold | "Hold" suffix only |
| Knees to Chest | Hanging Knee Raise | same movement — bringing knees toward chest while hanging |
| Pistol (alternating) | Pistol Squat | alternating legs between reps is not a distinct movement |
| Burpee Over Bar | Bar Facing Burpee (newly added) | same lateral-hop-over-bar burpee; Evox's own two names for one movement, kept the more standard CrossFit term |

## The swim/erg load_type decision and rationale
- **Swim**: `movement_pattern="row"` (not `run` or `bike`) — reasoned that swim propulsion is arm-pull/drive dominant, closest in kind to the existing `row` pattern already used for the other engine-based endurance movements (SkiErg, Rowing (Ergometer)). All three of `run`/`row`/`bike` collapse to the same `locomotion` `pattern_family` downstream (`app/scripts/seed_exercises.py:36-37`), so this choice has no behavioral effect beyond the raw `movement_pattern` string itself — flagging as a low-stakes but genuinely arbitrary judgment call. `load_type="distance"` per the task's own instruction (no swim-specific load_type exists; `distance` is the closer of `distance`/`time` since swims are conventionally programmed by meters). `modality="Conditioning"` to match the existing erg-machine precedent (Assault Bike / Rowing (Ergometer) / SkiErg are all `Conditioning`, not `Running`).
- **Bike Erg**: distinct equipment from the existing `Assault Bike` (a stationary spin/erg bike vs. a fan bike) — genuinely absent as its own row. Reused the existing `bike` equipment tag (already used on `Echo Bike Intervals`) rather than inventing `bike_erg`, since equipment values were constrained to already-in-use vocabulary. `load_type="distance"` matching Row/Ski precedent.

## Field mapping / vocabulary check
No new value was introduced in any constrained field. Verified sets identical before/after: `sport_domains` (`conditioning, crossfit, grip, gymnastics, hyrox, running, strongman, weightlifting`), `equipment_required` (25 values, unchanged), `weak_point_tags` (50 values, unchanged), `modality` (`Strength, Hypertrophy, Power, Calisthenics, Conditioning, Running, Mixed`, unchanged), `load_type` (unchanged — used `distance`/`time`/`reps`/`bodyweight`/`dumbbell`/`barbell`/`kettlebell` only), `movement_pattern` (unchanged — used only the 14 values already in the distribution). No `e1rm_benchmark_code` set on any row.

## Acceptance Criteria Self-Check
- [x] ENDURANCE checked/added first (highest priority) — `app/data/exercise_bulk.py` `endurance_vocab` block; Swim genuinely absent (confirmed structural gap), Row/Run/Bike(Assault-Echo)/Ski Erg all matched existing rows and were skipped.
- [x] GYMNASTICS vocabulary deepened — `gymnastics_vocab` block, 15 rows, pull-up/HSPU/dip families covered where genuinely absent.
- [x] OLYMPIC vocabulary deepened — `olympic_vocab` block, 12 rows.
- [x] CARDIO vocabulary deepened — `cardio_vocab` block, 18 rows.
- [x] STRENGTH + uncategorized deepened — `strength_vocab` block, 11 rows.
- [x] Every intended add checked against the catalog for an existing row under a different name first; every skip recorded with its mapped existing name (32 judgment-call skips documented above, plus 50 trivial normalized-string exact matches).
- [x] Only already-in-use `modality` / `movement_pattern` / `equipment_required` / `weak_point_tags` / `sport_domains` / `load_type` values used — verified via before/after set comparison, identical.
- [x] No `e1rm_benchmark_code` set on any row.
- [x] Row contract followed — `_row` 10-positional + keyword-optional; `_BaseRow` used for `gymnastics_vocab` (fixed 10-tuple, matches the neighboring `gym` block's idiom exactly); `_VariantRow` used for the other four blocks (trailing `sport_domains` and optional `unilateral` via `*rest`), matching `gap_fill`/`pull_horizontal_extra`/`push_vertical_extra`'s idiom.
- [x] No name collisions — 206 unique bulk rows (147 + 59), 262 unique across `EXERCISES + bulk_exercises()` (203 + 59).
- [x] No alembic migration added; `app/scripts/seed_exercises.py` untouched.

## Test Results
```
$ .venv/Scripts/python.exe -c "from app.data.exercise_bulk import bulk_exercises; r=bulk_exercises(); print(len(r)); assert len({x['name'] for x in r})==len(r)"
bulk rows: 206
no dup in bulk: OK

$ .venv/Scripts/python.exe -c "... EXERCISES+bulk_exercises() dedup check ..."
total: 262 unique: 262
cross-file: OK

$ .venv/Scripts/python.exe -m pytest tests/test_prescribed_exercise_names_resolve.py -v
tests/test_prescribed_exercise_names_resolve.py::test_every_prescribable_exercise_name_resolves PASSED
tests/test_prescribed_exercise_names_resolve.py::test_known_gaps_are_actually_still_missing PASSED
tests/test_prescribed_exercise_names_resolve.py::test_known_gaps_are_all_actually_referenced PASSED
tests/test_prescribed_exercise_names_resolve.py::test_the_catalog_is_reachable_at_all PASSED
4 passed in 0.16s

$ .venv/Scripts/python.exe -m ruff check app/data/exercise_bulk.py
All checks passed!

$ .venv/Scripts/python.exe -m pyright app/data/exercise_bulk.py
0 errors, 0 warnings, 0 informations
```

## movement_pattern / modality distribution, `EXERCISES + bulk_exercises()`, before vs after
```
BEFORE (203 rows):
movement_pattern: hinge 31, squat 20, push_vertical 17, pull_vertical 17, core 17, mixed 17,
  push_horizontal 16, single_leg 15, carry 15, run 13, pull_horizontal 12, jump 7, row 4, bike 2
modality: Strength 68, Hypertrophy 36, Power 33, Calisthenics 30, Conditioning 20, Running 10, Mixed 6

AFTER (262 rows):
movement_pattern: hinge 38, mixed 27, squat 24, single_leg 23, push_vertical 23, core 22,
  pull_vertical 21, push_horizontal 19, run 16, carry 15, pull_horizontal 14, jump 12, row 5, bike 3
modality: Strength 77, Calisthenics 48, Power 46, Hypertrophy 37, Conditioning 35, Running 12, Mixed 7
```
Biggest movers: `mixed` +10 (17→27, mostly Olympic complexes and burpee-family cardio), `single_leg` +8 (15→23, lunge family), `jump` +5 (7→12, under-family and box-jump-over movements), `push_vertical` +6 (HSPU family), `core` +5 (sit-up/V-up/Mountain Climber), `pull_vertical` +4 (pull-up family), `row`/`bike` +1 each (Swim mapped to `row`, Bike Erg to `bike`).

## Known Gaps / Notes for Critic — judgment calls worth second-guessing
1. **`Strict Pull-up` skipped, not added.** This is the one place I diverged from a literal reading of the task's GYMNASTICS vocabulary list (which named "Strict/Kipping/Butterfly/Chest-to-Bar/L-sit/Weighted" as the pull-up family to add). I concluded the existing `Pull-up` row already *is* the strict variant — its coaching note is "Full hang to chin over bar" (no kip language) and its skill_demand (0.5) matches the task's own calibration anchor "`Pull-up` ~0.5" for skill_demand. Applying the same logic used elsewhere (`Strict Press`→`Overhead Press`, `Strict Handstand Push-up`→`Handstand Push-up`, `Strict Ring Dip`→`Ring Dip`, all confirmed-correct patterns), a fourth `Strict Pull-up` row alongside the existing generic `Pull-up` would be a near-duplicate. If a reviewer disagrees and reads plain `Pull-up` as kip-agnostic/ambiguous rather than strict, this is a one-row fix (add `Strict Pull-up` with skill≈0.55).
2. **`Swim`'s `movement_pattern="row"`** — arbitrary between `row`/`run`/`bike` (all three map to the same `locomotion` pattern_family downstream, so no functional difference), but still a naming choice a reviewer might want changed to `run` for a more "endurance-generic" read.
3. **`Squat Clean` marked `is_benchmark=False`** (default). Squat Clean is commonly tracked as its own e1RM/benchmark lift in practice, similar to how `Clean and Jerk` and `Snatch (Full)` are marked `is_benchmark=True` in this catalog. I left it `False` to avoid expanding scope/behavior beyond "add the row" — flagging in case a reviewer wants it flipped to `True` (task explicitly said not to set `e1rm_benchmark_code`, which I didn't; `is_benchmark` is a separate boolean I chose not to touch).
4. **`Bike Erg` reuses the existing `bike` equipment tag** (already used on `Echo Bike Intervals`) rather than a `bike_erg`-specific tag, since equipment values were constrained to already-in-use vocabulary — this means `Bike Erg` and `Assault Bike` are now equipment-distinguishable (`bike` vs `assault_bike`) but `Bike Erg` and `Echo Bike Intervals` are not, even though mechanically Echo Bike is a fan bike (same family as Assault Bike) and Bike Erg is a seated stationary erg. Pre-existing inconsistency in the `bike`/`assault_bike` tagging, not something I introduced or fixed (out of scope — `Echo Bike Intervals` is untouched).
5. **`Burpee Over Bar` skipped as a duplicate of newly-added `Bar Facing Burpee`** rather than of an *existing* catalog row — Evox itself lists these as two separate movements with identical category/difficulty (`Ci`/`Ci`), which read to me as Evox's own naming redundancy for the same lateral-hop-over-bar burpee. If a reviewer judges these genuinely distinct (e.g. facing-vs-perpendicular orientation), this is a one-row addition.
6. No new dependencies introduced.
