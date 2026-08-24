"""Load the High-Intensity Strength Training log into per-set workout entries.

Kaggle slug ``aridoge13/high-intensity-strength-training-data``: one lifter, Dec 2025 –
Jul 2026, exported from the Hevy app. 61 sessions, 251 set rows, CC BY 4.0 (commercial
use permitted, unlike PMData).

WHY IT IS HERE. PMData supplies real subjective wellness and a real *session* RPE, but no
set detail — so ``total_volume_load``, ``estimated_sets`` and ``avg_rir`` stayed invented.
This corpus is the opposite shape: no check-ins at all, but every set carries real weight,
reps and RPE. Feeding it through ``WorkoutLog.sets`` means the dose engine computes from
genuine external load, per-set rows land in ``workout_set_logs``, and top sets emit real
e1RM observations (ADR-0045) rather than the bodyweight-multiplier estimates
``seed_demo_athletes`` fabricates.

EXERCISE BINDING IS DELIBERATELY CONSERVATIVE. Hevy names are not catalog names, and a
wrong binding is worse than no binding: it would attribute a machine's load to a free-weight
e1RM and move the athlete's capacity on evidence that does not support it. Only movements
that are genuinely the same lift are bound (see ``_CATALOG_NAMES``); everything else — smith
bars, machine presses, dumbbell variants — logs via ``free_text_name``, which the service
treats as having no benchmark linkage. That is the honest outcome, not a gap to close later.

Consequence worth stating plainly: of 251 sets, only the barbell squat and barbell deadlift
sets can produce e1RM observations. That is a small number of REAL data points replacing a
larger number of invented ones.

SESSION RPE IS DERIVED, NOT REPORTED. Hevy records per-SET RPE; it has no session rating.
``session_rpe`` here is the mean of the session's working-set RPEs, which is a different
construct from PMData's ``perceived_exertion`` (a single post-session judgement). It is
required by ``WorkoutLog`` and this is the most defensible derivation available — but it is
a derivation, and the raw per-set values are preserved so nothing is lost.

RIR comes from RPE as ``10 - rpe`` on the Borg CR-10 convention the dataset documents
("10 = maximal effort, no reps left"). Rows with no RPE get no RIR rather than zero.

Run (prints a summary, writes nothing):
    python -m app.scripts.load_hit_strength
"""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date as date_cls
from datetime import datetime
from pathlib import Path
from typing import Any

_ROOT = Path("data/kaggle/hit-strength")
_WORKOUTS = _ROOT / "cleaned_workouts.csv"
_MEASUREMENTS = _ROOT / "measurement_data_cleaned.csv"

SOURCE = "hit_strength"

#: Hevy export stamps "27 Jul 2026, 18:09".
_TS_FORMAT = "%d %b %Y, %H:%M"

#: The data card states blank weight means a bodyweight movement performed at ~80 kg.
_BODYWEIGHT_KG = 80.0

#: Hevy name -> catalog name. ONLY where the movement is genuinely the same lift.
#: Smith-bar, machine-press and dumbbell variants are intentionally absent: binding them
#: would move a free-weight capacity axis on evidence about a different movement.
_CATALOG_NAMES = {
    "Squat (Barbell)": "Back Squat",            # carries pl_e1rm_squat
    "Deadlift (Barbell)": "Conventional Deadlift",  # carries pl_e1rm_deadlift
    "Leg Press (Machine)": "Leg Press",
    "Leg Extension (Machine)": "Leg Extension",
    "Single Leg Extensions": "Leg Extension",
    "Lying Leg Curl (Machine)": "Leg Curl",
    "Reverse Grip Lat Pulldown (Cable)": "Lat Pulldown",
    "Preacher Curl (Barbell)": "Preacher Curl",
    # "Bicep Curl (Barbell)" is deliberately unmapped: the catalog has no plain barbell
    # curl (only Hammer / Preacher / Nordic / Jefferson / Leg), and Hammer Curl is a
    # different grip. tests/test_load_hit_strength.py pins that every name here exists.
}


@dataclass
class HitSet:
    """One logged set. ``catalog_name`` is None when the movement has no safe binding."""

    catalog_name: str | None
    free_text_name: str | None
    load_kg: float | None
    reps: int | None
    rpe: float | None
    rir: float | None
    is_working_set: bool


@dataclass
class HitSession:
    day: date_cls
    started_at: datetime
    ended_at: datetime
    duration_minutes: float
    session_rpe: float
    total_volume_load: float
    avg_rir: float | None
    sets: list[HitSet] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


def _float(value: str | None) -> float | None:
    if value is None or not value.strip():
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _ts(value: str) -> datetime | None:
    text = (value or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, _TS_FORMAT)
    except ValueError:
        return None


def load_bodyweights(root: Path | None = None) -> dict[date_cls, float]:
    """The lifter's measured bodyweight by date — a real series, not a formula."""
    path = (root or _ROOT) / _MEASUREMENTS.name
    if not path.is_file():
        return {}
    out: dict[date_cls, float] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            weight = _float(row.get("body_weight_kg"))
            stamp = (row.get("date") or "").strip()
            if weight is None or not stamp:
                continue
            try:
                out[date_cls.fromisoformat(stamp)] = weight
            except ValueError:
                continue
    return out


def load_sessions(root: Path | None = None) -> list[HitSession]:
    """Group the per-set export into sessions, preserving every real per-set value."""
    path = (root or _ROOT) / _WORKOUTS.name
    if not path.is_file():
        raise SystemExit(
            "hit-strength not found under data/kaggle/hit-strength/. Run: "
            "python -m app.scripts.download_new_datasets --only hit-strength"
        )

    grouped: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            grouped[(row.get("start_time", ""), row.get("title", ""))].append(row)

    sessions: list[HitSession] = []
    for (start_raw, title), rows in grouped.items():
        started = _ts(start_raw)
        ended = _ts(rows[0].get("end_time", ""))
        if started is None or ended is None:
            continue

        duration = (ended - started).total_seconds() / 60.0
        if duration <= 0:
            continue

        entries: list[HitSet] = []
        volume = 0.0
        working_rpes: list[float] = []

        for row in rows:
            hevy_name = (row.get("exercise_title") or "").strip()
            catalog = _CATALOG_NAMES.get(hevy_name)
            rpe = _float(row.get("rpe"))
            reps_f = _float(row.get("reps"))
            reps = int(reps_f) if reps_f is not None else None
            # A blank weight is a bodyweight movement, per the dataset's own data card —
            # not a zero-load set.
            load = _float(row.get("weight_kg"))
            if load is None:
                load = _BODYWEIGHT_KG
            working = (row.get("set_type") or "").strip().lower() == "failure"

            if reps is not None:
                volume += load * reps
            if working and rpe is not None:
                working_rpes.append(rpe)

            entries.append(
                HitSet(
                    catalog_name=catalog,
                    free_text_name=None if catalog else (hevy_name or None),
                    load_kg=load,
                    reps=reps,
                    rpe=rpe,
                    # Borg CR-10: 10 = nothing left. No RPE means no RIR, never zero.
                    rir=max(0.0, 10.0 - rpe) if rpe is not None else None,
                    is_working_set=working,
                )
            )

        if not entries:
            continue

        # Derived, not reported — see module docstring. Falls back to the CR-10 top of the
        # scale only when the session recorded no RPE at all, which for an all-out
        # protocol is the dataset's own documented default.
        session_rpe = (
            round(sum(working_rpes) / len(working_rpes), 1) if working_rpes else 10.0
        )
        rirs = [e.rir for e in entries if e.rir is not None]

        sessions.append(
            HitSession(
                day=ended.date(),
                started_at=started,
                ended_at=ended,
                duration_minutes=round(duration, 1),
                session_rpe=session_rpe,
                total_volume_load=round(volume, 1),
                avg_rir=round(sum(rirs) / len(rirs), 2) if rirs else None,
                sets=entries,
                raw={
                    "dataset": "kaggle:aridoge13/high-intensity-strength-training-data",
                    "workout_title": title,
                    "session_rpe_is_derived": "mean of working-set RPE; Hevy logs no session rating",
                },
            )
        )

    sessions.sort(key=lambda s: s.ended_at)
    return sessions


def main() -> None:
    argparse.ArgumentParser(description="Summarize the hit-strength corpus (reads only)").parse_args()

    sessions = load_sessions()
    bodyweights = load_bodyweights()
    total_sets = sum(len(s.sets) for s in sessions)
    bound = sum(1 for s in sessions for e in s.sets if e.catalog_name)
    e1rm_capable = sum(
        1
        for s in sessions
        for e in s.sets
        if e.catalog_name in ("Back Squat", "Conventional Deadlift", "Bench Press")
    )
    unbound_names = sorted({e.free_text_name for s in sessions for e in s.sets if e.free_text_name})

    span = f"{sessions[0].day} -> {sessions[-1].day}" if sessions else "n/a"
    print(f"{len(sessions)} sessions, {total_sets} sets, {span}")
    print(f"  bound to catalog exercises : {bound}")
    print(f"  can emit an e1RM observation: {e1rm_capable}")
    print(f"  free-text (no benchmark linkage): {total_sets - bound}")
    print(f"  measured bodyweights: {len(bodyweights)}")
    print(f"  total volume load: {sum(s.total_volume_load for s in sessions):,.0f} kg")
    print("\nunbound movements (deliberate — no safe catalog equivalent):")
    for name in unbound_names:
        print(f"  {name}")
    print("\nLicence: CC BY 4.0 (commercial use permitted).")


if __name__ == "__main__":
    main()
