"""The hit-strength loader turns a per-set export into honest workout entries.

Two classes of failure are guarded here.

**A mapping to a catalog exercise that does not exist.** ``_CATALOG_NAMES`` is a hand-written
Hevy-name -> catalog-name dict, and nothing else checks it: a typo or a plausible-but-absent
name (``Barbell Curl`` is NOT in this catalog — only Hammer / Preacher / Nordic / Jefferson /
Leg) would bind to nothing and silently drop that exercise's evidence.

**Inventing values the export does not contain.** A blank weight is a bodyweight movement,
not a zero-load set; a set with no RPE has no RIR rather than a RIR of zero; and
``session_rpe`` is DERIVED from per-set RPE here, which is a different construct from
PMData's reported session rating.

The parsing tests build a small fixture so they run without the download; the catalog test
needs the seeded exercise table.
"""
from __future__ import annotations

import csv
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.exercise import Exercise
from app.scripts import load_hit_strength
from app.scripts.load_hit_strength import _CATALOG_NAMES

_HEADER = [
    "title", "start_time", "end_time", "exercise_title", "superset_id",
    "set_index", "set_type", "weight_kg", "reps", "rpe",
]


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    rows = [
        # one session, three sets: a bound barbell lift, a blank-weight bodyweight movement,
        # and a set with no RPE logged.
        ["Legs", "05 Mar 2026, 18:00", "05 Mar 2026, 18:40",
         "Squat (Barbell)", "", 0, "failure", 100.0, 5.0, 10.0],
        ["Legs", "05 Mar 2026, 18:00", "05 Mar 2026, 18:40",
         "Triceps Dip", "", 0, "failure", "", 12.0, 8.0],
        ["Legs", "05 Mar 2026, 18:00", "05 Mar 2026, 18:40",
         "Calf Press (Machine)", "", 0, "failure", 200.0, 10.0, ""],
        # a second, later session
        ["Chest", "12 Mar 2026, 19:00", "12 Mar 2026, 19:25",
         "Chest Fly (Machine)", "", 0, "failure", 80.0, 7.0, 9.0],
    ]
    with (tmp_path / "cleaned_workouts.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(_HEADER)
        w.writerows(rows)
    with (tmp_path / "measurement_data_cleaned.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["date", "body_weight_kg", "waist_cm"])
        w.writerow(["2026-03-05", 78.0, 87.5])
    return tmp_path


def test_sessions_group_by_start_time(corpus: Path) -> None:
    sessions = load_hit_strength.load_sessions(corpus)
    assert len(sessions) == 2
    assert [len(s.sets) for s in sessions] == [3, 1]
    # ordered oldest-first, so a replay preserves the real progression
    assert sessions[0].day < sessions[1].day
    assert sessions[0].duration_minutes == 40.0


def test_blank_weight_is_bodyweight_not_zero(corpus: Path) -> None:
    """The data card says a blank weight is a bodyweight movement (~80 kg)."""
    dip = load_hit_strength.load_sessions(corpus)[0].sets[1]
    assert dip.load_kg == 80.0, "a blank weight must not become a zero-load set"


def test_missing_rpe_gives_no_rir(corpus: Path) -> None:
    """No RPE means we do not know the RIR — not that the lifter had zero reps left."""
    calf = load_hit_strength.load_sessions(corpus)[0].sets[2]
    assert calf.rpe is None
    assert calf.rir is None, "absent RPE must not be turned into RIR 0"


def test_rir_derives_from_rpe_on_cr10(corpus: Path) -> None:
    squat, dip, _ = load_hit_strength.load_sessions(corpus)[0].sets
    assert squat.rpe == 10.0 and squat.rir == 0.0  # nothing left in the tank
    assert dip.rpe == 8.0 and dip.rir == 2.0


def test_volume_load_uses_real_weight_and_reps(corpus: Path) -> None:
    session = load_hit_strength.load_sessions(corpus)[0]
    # 100*5 + 80*12 (bodyweight) + 200*10 = 500 + 960 + 2000
    assert session.total_volume_load == 3460.0


def test_session_rpe_is_the_mean_of_working_sets(corpus: Path) -> None:
    """Derived, not reported — Hevy logs no session rating. The set values survive in `sets`."""
    session = load_hit_strength.load_sessions(corpus)[0]
    assert session.session_rpe == 9.0  # mean of 10.0 and 8.0; the no-RPE set is excluded
    assert session.raw["session_rpe_is_derived"].startswith("mean of working-set RPE")


def test_only_safe_movements_bind_to_the_catalog(corpus: Path) -> None:
    """A machine or smith variant must not claim a free-weight lift's benchmark."""
    squat, dip, calf = load_hit_strength.load_sessions(corpus)[0].sets
    assert squat.catalog_name == "Back Squat" and squat.free_text_name is None
    # These have no safe equivalent: they log as free text, which carries no benchmark linkage.
    assert dip.catalog_name is None and dip.free_text_name == "Triceps Dip"
    assert calf.catalog_name is None and calf.free_text_name == "Calf Press (Machine)"


def test_smith_and_machine_presses_are_not_mapped() -> None:
    """Pinned as a decision: binding these would move a free-weight axis on other evidence."""
    for hevy_name in (
        "Bench Press (Smith Machine)",
        "Incline Bench Press (Smith Machine)",
        "Squat (Machine)",
        "Bicep Curl (Barbell)",
    ):
        assert hevy_name not in _CATALOG_NAMES, f"{hevy_name} must stay unbound"


def test_bodyweights_are_read_not_derived(corpus: Path) -> None:
    from datetime import date

    weights = load_hit_strength.load_bodyweights(corpus)
    assert weights[date(2026, 3, 5)] == 78.0


@pytest.mark.asyncio
async def test_every_mapped_catalog_name_exists(
    async_db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The guard that catches a plausible-but-absent catalog name.

    This is a real bug this test caught during development: ``Bicep Curl (Barbell)`` was
    mapped to ``Barbell Curl``, which this catalog does not have. A mapping that resolves
    to nothing binds the set to no exercise and silently discards its benchmark linkage.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.scripts import seed_benchmarks, seed_exercises

    # The seeders open their own session; point it at this worker's test database.
    test_factory = async_sessionmaker(async_db.bind, expire_on_commit=False)
    monkeypatch.setattr(seed_benchmarks, "AsyncSessionLocal", test_factory)
    monkeypatch.setattr(seed_exercises, "AsyncSessionLocal", test_factory)

    await seed_benchmarks.seed()
    await seed_exercises.seed()
    await async_db.rollback()

    known = set(
        (await async_db.execute(select(Exercise.name))).scalars().all()
    )
    missing = sorted(name for name in _CATALOG_NAMES.values() if name not in known)
    assert not missing, f"_CATALOG_NAMES maps to exercises that do not exist: {missing}"
