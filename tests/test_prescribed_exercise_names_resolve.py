"""Every exercise name the prescriber can emit must resolve to a catalog row.

Template slots now state requirements and the catalog answers them (ADR-0016), so templates no
longer name anything. What remains name-based is the fallback the prescriber uses when a
template declares no slots: `_EQUIPMENT_EXERCISE_MAP`, `_ACCESSORY_BY_TAG` and
`_GENERIC_ACCESSORIES`. Those strings are joined back to the catalog by
EXACT, case-sensitive name (`prescription_service._e1rm_codes_for_names`,
`_weak_point_tags_for_names`, `state_service._resolve_exercise_phis`).

When a name misses, nothing raises. The athlete is prescribed an exercise that silently gets:

  * no `percent_e1rm` and no `prescribed_load_kg` — the load lookup needs the catalog row's
    `e1rm_benchmark_code` (`prescription_service.py:311-312` just `continue`s);
  * no `weak_point_tags` — so the "why this exercise" explanation is empty for it;
  * no catalog phi when the log is seeded from `prescribed_content` — the dose engine falls
    back to a generic modality default (`state_service.py:500-501`, `dose_engine_v0.py:203-224`).

28 of 46 names were unresolved when this guard was written. 17 were pure naming drift against a
catalog that already had the movement — `"Pull-Up"` vs `"Pull-up"`, `"Deadlift"` vs
`"Conventional Deadlift"`, `"Clean & Jerk"` vs `"Clean and Jerk"` — and were fixed by renaming.
Migrating templates to requirement-based slots then removed most of the remaining surface.

The rest are real catalog gaps and are listed in `KNOWN_CATALOG_GAPS` below. That list is
SHRINK-ONLY: adding the missing exercise removes an entry, and a NEW unresolved name fails
this test rather than quietly costing an athlete their load prescription.
"""
from __future__ import annotations

from app.data.exercise_bulk import bulk_exercises
from app.logic import prescriber
from app.scripts.seed_exercises import EXERCISES

#: Movements the prescriber names that the catalog does not contain. Each needs a real
#: catalog row (name + modality + movement_pattern + load_type, plus skill_demand and
#: impact_level to shape phi) before it can be dose-correct or load-prescribed.
#:
#: SHRINK-ONLY. Do not add to this list to make a failure go away — either add the exercise
#: to the catalog, or point the template at a movement that already exists.
KNOWN_CATALOG_GAPS: frozenset[str] = frozenset()


def _catalog_names() -> set[str]:
    """Names the seeder will create. Read from source, so this needs no database."""
    return {row["name"] for row in EXERCISES} | {row["name"] for row in bulk_exercises()}


def _prescribable_names() -> dict[str, set[str]]:
    """Every exercise name the prescriber can emit, mapped to where it is declared."""
    used: dict[str, set[str]] = {}

    def note(name: str, where: str) -> None:
        used.setdefault(name, set()).add(where)

    # Templates no longer name exercises — their slots state requirements and the catalog
    # answers them (see app/logic/exercise_slot.py). What remains name-based is the
    # equipment/accessory fallback, which still joins to the catalog by exact string.
    for equipment, items in prescriber._EQUIPMENT_EXERCISE_MAP.items():
        for item in items:
            note(item[0], f"equipment:{equipment}")
    for tag, items in prescriber._ACCESSORY_BY_TAG.items():
        for item in items:
            note(item[0], f"accessory:{tag}")
    for item in prescriber._GENERIC_ACCESSORIES:
        note(item[0], "generic_accessory")
    return used


def test_every_prescribable_exercise_name_resolves() -> None:
    """The guard. A new unresolved name fails here, not silently in production."""
    catalog = _catalog_names()
    used = _prescribable_names()

    unresolved = {
        name: sorted(where)
        for name, where in used.items()
        if name not in catalog and name not in KNOWN_CATALOG_GAPS
    }

    assert not unresolved, (
        "Prescriber names exercises that are not in the catalog, so they will silently get "
        "no load, no weak-point tags and no catalog phi:\n"
        + "\n".join(f"  {n!r} declared in {w}" for n, w in sorted(unresolved.items()))
        + "\nEither add the exercise to app/scripts/seed_exercises.py (or exercise_bulk.py), "
        "or point the slot at a movement the catalog already has. Do NOT add it to "
        "KNOWN_CATALOG_GAPS to silence this — that list is shrink-only."
    )


def test_known_gaps_are_actually_still_missing() -> None:
    """Ratchet: once a gap is filled, its entry must be deleted.

    Without this the allowlist would quietly outlive the problem and start hiding regressions
    for names that DO resolve — the same rot the shrink-only comment is trying to prevent.
    """
    catalog = _catalog_names()
    now_present = sorted(name for name in KNOWN_CATALOG_GAPS if name in catalog)

    assert not now_present, (
        "These are in KNOWN_CATALOG_GAPS but the catalog now has them — delete them from the "
        f"list: {now_present}"
    )


def test_known_gaps_are_all_actually_referenced() -> None:
    """A gap nobody names is not a gap; it is dead weight in the allowlist."""
    used = _prescribable_names()
    unreferenced = sorted(name for name in KNOWN_CATALOG_GAPS if name not in used)

    assert not unreferenced, (
        "KNOWN_CATALOG_GAPS lists names the prescriber no longer emits — remove them: "
        f"{unreferenced}"
    )


def test_the_catalog_is_reachable_at_all() -> None:
    """Positive control: the join is name-based, so prove real names actually match.

    If this ever fails the test above is meaningless — it would be passing because nothing
    resolves rather than because everything does.
    """
    catalog = _catalog_names()
    used = _prescribable_names()
    resolved = [name for name in used if name in catalog]

    assert len(resolved) >= 8, (
        f"only {len(resolved)} of {len(used)} prescribable names resolve — the catalog join "
        "is broken, not merely incomplete"
    )
