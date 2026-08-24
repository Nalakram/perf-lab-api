"""Load the PMData sports-logging dataset into the canonical wellness vocabulary.

PMData (Simula / PMSys, Kaggle slug ``vlbthambawita/pmdata-a-sports-logging-dataset``)
is 16 participants over five months. It matters because it is the ONLY corpus in
``data/kaggle/`` that carries the subjective fields this system models on:

    soreness  — the only EKF-assimilated wellness signal
    stress, mood
    perceived_exertion — session RPE, a REQUIRED field on WorkoutLog

Every other dataset here is objective (heart rate, steps, sleep) or cross-sectional, so
those four fields were previously invented — by RNG in ``seed_shadow_history`` and by
constant lookup tables in ``seed_fitbit_workout_logs`` / ``seed_gym_members_wellness``.

It also fixes a subtler problem. Every existing wellness↔workout pairing in this repo is
round-robin across unrelated subjects, so an athlete's check-in and their session come
from two different real humans. PMData is per-participant (``p01``…``p16``): one person's
morning check-in and that same person's session, same day. That linkage is what the twin
actually models, and nothing else on disk has it.

SCALE DIRECTION — the load-bearing detail. PMSys scores fatigue / mood / sleep_quality /
soreness / stress on 1–5 where **higher is better** (3 = normal, 4–5 above normal). This
system's ``soreness`` and ``stress`` are 0–10 where **higher is worse**. So both are
INVERTED here, while ``mood`` (higher = better on both) is only rescaled.

That direction is not taken on faith. ``soreness_area`` — the body region the participant
tagged — is named on 100% of rows scoring soreness=1 and 89% scoring 2, versus 0.1% at 3
and 0% at 4–5. Low score = actually sore. Verified against all 1,747 rows, 2026-08-24.

A ZERO IS NOT AN ANSWER. The documented scale starts at 1, but a handful of rows carry 0
(2–4 rows per field). Those are unanswered questions, and this loader returns ``None`` for
them rather than mapping 0 to the worst-possible score — that would be the
missing-becomes-a-number defect this codebase has repeatedly had to remove.

``fatigue`` and ``readiness`` have no field in this system's wellness vocabulary; they are
preserved in ``raw`` for provenance rather than discarded or forced into a nearby field.

LICENCE: PMData is CC BY-NC 4.0 — NON-COMMERCIAL. Fine for validating the pipeline; check
before using it to calibrate anything shipped.

Run (prints a summary, writes nothing):
    python -m app.scripts.load_pmdata
    python -m app.scripts.load_pmdata --participant p03
"""

from __future__ import annotations

import argparse
import ast
import csv
from dataclasses import dataclass, field
from datetime import date as date_cls
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from app.integrations.base import NormalizedWellness

#: kagglehub unpacks the OSF archive one level down; tolerate both shapes.
_ROOTS = (
    Path("data/kaggle/pmdata/osfstorage-archive/pmdata"),
    Path("data/kaggle/pmdata/pmdata"),
    Path("data/kaggle/pmdata"),
)

SOURCE = "pmdata"

#: PMSys 1–5 Likert. 0 appears in a few rows and is NOT a valid answer.
_LIKERT_LO, _LIKERT_HI = 1.0, 5.0

Modality = Literal["Running", "Strength", "Hypertrophy", "Power", "Mixed"]

_AEROBIC_TAGS = frozenset({"running", "endurance", "cycling", "swimming", "soccer", "cardio"})
_STRENGTH_TAGS = frozenset({"strength", "weightlifting", "gym"})


@dataclass
class PMDataSession:
    """One logged training session from ``srpe.csv``.

    ``perceived_exertion`` is already a Borg CR-10 rating (verified 1–10 across all 783
    rows), which is exactly ``WorkoutLog.session_rpe``'s domain — so it is carried across
    unscaled. This is the only real session-RPE source in the repo.
    """

    day: date_cls
    ended_at: datetime
    session_rpe: float
    duration_minutes: float
    modality: Modality
    raw: dict[str, Any] = field(default_factory=dict)


def _root() -> Path:
    for candidate in _ROOTS:
        if candidate.is_dir() and any(candidate.glob("p*/pmsys/wellness.csv")):
            return candidate
    raise SystemExit(
        "PMData not found under data/kaggle/pmdata/. "
        "Run: python -m app.scripts.download_new_datasets --only pmdata"
    )


def participants(root: Path | None = None) -> list[str]:
    base = root or _root()
    return sorted(p.name for p in base.glob("p*") if (p / "pmsys" / "wellness.csv").is_file())


def _likert(value: str | None) -> float | None:
    """A PMSys 1–5 answer, or None when unanswered.

    Anything outside 1–5 — including the 0 that a few rows carry — is treated as absent.
    Clamping 0 up to 1 would assert the worst possible score for a question nobody answered.
    """
    if value is None or not value.strip():
        return None
    try:
        parsed = float(value)
    except ValueError:
        return None
    if not (_LIKERT_LO <= parsed <= _LIKERT_HI):
        return None
    return parsed


def _invert_to_ten(value: float | None) -> float | None:
    """PMSys 1–5 higher-is-better → this system's 0–10 higher-is-WORSE."""
    if value is None:
        return None
    return round((_LIKERT_HI - value) * 2.5, 2)


def _rescale_to_ten(value: float | None) -> float | None:
    """PMSys 1–5 higher-is-better → 0–10 higher-is-better. Direction preserved."""
    if value is None:
        return None
    return round((value - _LIKERT_LO) * 2.5, 2)


def _rescale_to_hundred(value: float | None) -> float | None:
    """PMSys 1–5 sleep quality → this system's 0–100 higher-is-better."""
    if value is None:
        return None
    return round((value - _LIKERT_LO) * 25.0, 2)


def _positive_float(value: str | None) -> float | None:
    if value is None or not value.strip():
        return None
    try:
        parsed = float(value)
    except ValueError:
        return None
    return parsed if parsed > 0 else None


def _parse_ts(value: str) -> datetime | None:
    """PMSys stamps ISO8601 with a trailing Z. Store naive UTC, as the models do."""
    text = (value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=None) if parsed.tzinfo is None else parsed.astimezone().replace(tzinfo=None)


def _tags(raw_value: str) -> list[str]:
    """``activity_names`` is a stringified python list, e.g. ``['individual', 'running']``."""
    text = (raw_value or "").strip()
    if not text:
        return []
    try:
        parsed = ast.literal_eval(text)
    except (ValueError, SyntaxError):
        return []
    if not isinstance(parsed, (list, tuple)):
        return []
    return [str(t).strip().lower() for t in parsed]


def _modality(tags: list[str]) -> Modality:
    """Map PMSys activity tags onto this system's modality vocabulary.

    A session tagged both strength and aerobic is Mixed rather than being forced into
    whichever tag happens to be read first.
    """
    has_strength = any(t in _STRENGTH_TAGS for t in tags)
    has_aerobic = any(t in _AEROBIC_TAGS for t in tags)
    if has_strength and has_aerobic:
        return "Mixed"
    if has_strength:
        return "Strength"
    if has_aerobic:
        return "Running"
    return "Mixed"


def load_wellness(participant: str, root: Path | None = None) -> list[NormalizedWellness]:
    """One participant's daily check-ins, in the canonical wellness vocabulary."""
    base = root or _root()
    path = base / participant / "pmsys" / "wellness.csv"
    if not path.is_file():
        return []

    out: list[NormalizedWellness] = []
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            stamped = _parse_ts(row.get("effective_time_frame", ""))
            if stamped is None:
                continue

            soreness_area = (row.get("soreness_area") or "").strip()
            raw: dict[str, Any] = {
                "dataset": "kaggle:vlbthambawita/pmdata-a-sports-logging-dataset",
                "participant": participant,
                # No field in this system's vocabulary; kept rather than dropped.
                "pmsys_fatigue_1_5": _likert(row.get("fatigue")),
                "pmsys_readiness_0_10": _positive_float(row.get("readiness")),
                "pmsys_soreness_1_5": _likert(row.get("soreness")),
            }
            if soreness_area and soreness_area != "[]":
                raw["soreness_area"] = soreness_area

            out.append(
                NormalizedWellness(
                    day=stamped.date(),
                    hrv_ms=None,  # PMData's Fitbit Versa 2 does not expose rMSSD
                    sleep_hours=_positive_float(row.get("sleep_duration_h")),
                    sleep_quality=_rescale_to_hundred(_likert(row.get("sleep_quality"))),
                    resting_hr=None,  # lives in fitbit/resting_heart_rate.json, not here
                    soreness=_invert_to_ten(_likert(row.get("soreness"))),
                    mood=_rescale_to_ten(_likert(row.get("mood"))),
                    stress=_invert_to_ten(_likert(row.get("stress"))),
                    measured_at=stamped,
                    quality=None,  # PMSys reports no reliability signal of its own
                    raw=raw,
                )
            )
    return out


def load_sessions(participant: str, root: Path | None = None) -> list[PMDataSession]:
    """One participant's logged training sessions, with real perceived exertion."""
    base = root or _root()
    path = base / participant / "pmsys" / "srpe.csv"
    if not path.is_file():
        return []

    out: list[PMDataSession] = []
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            ended = _parse_ts(row.get("end_date_time", ""))
            rpe = _positive_float(row.get("perceived_exertion"))
            duration = _positive_float(row.get("duration_min"))
            if ended is None or rpe is None or duration is None:
                continue
            # WorkoutLog bounds session_rpe to 1..10; anything outside is not a CR-10 answer.
            if not (1.0 <= rpe <= 10.0):
                continue

            tags = _tags(row.get("activity_names", ""))
            out.append(
                PMDataSession(
                    day=ended.date(),
                    ended_at=ended,
                    session_rpe=rpe,
                    duration_minutes=duration,
                    modality=_modality(tags),
                    raw={
                        "dataset": "kaggle:vlbthambawita/pmdata-a-sports-logging-dataset",
                        "participant": participant,
                        "activity_names": tags,
                    },
                )
            )
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Summarize the PMData corpus (reads only)")
    ap.add_argument("--participant", default=None, help="e.g. p03; default: all")
    args = ap.parse_args()

    base = _root()
    names = [args.participant] if args.participant else participants(base)

    total_w = total_s = with_soreness = with_stress = skipped = 0
    for name in names:
        wellness = load_wellness(name, base)
        sessions = load_sessions(name, base)
        sore = sum(1 for w in wellness if w.soreness is not None)

        # Report what was dropped rather than letting it vanish: a silently shorter corpus
        # reads as "this participant trained less", which is a different claim entirely.
        srpe_path = base / name / "pmsys" / "srpe.csv"
        raw_sessions = 0
        if srpe_path.is_file():
            with srpe_path.open(newline="", encoding="utf-8") as handle:
                raw_sessions = sum(1 for _ in csv.DictReader(handle))
        dropped = raw_sessions - len(sessions)
        skipped += dropped

        total_w += len(wellness)
        total_s += len(sessions)
        with_soreness += sore
        with_stress += sum(1 for w in wellness if w.stress is not None)
        note = f"  [{dropped} session rows skipped: no RPE logged]" if dropped else ""
        print(
            f"  {name}: {len(wellness):4d} check-ins ({sore} with soreness), "
            f"{len(sessions):3d} sessions{note}"
        )

    print(
        f"\n{len(names)} participant(s): {total_w} check-ins, {with_soreness} with soreness, "
        f"{with_stress} with stress, {total_s} sessions with real RPE."
    )
    if skipped:
        print(
            f"{skipped} session row(s) skipped for having no perceived_exertion — session_rpe "
            "is required and unanswered is not zero."
        )
    print("Licence: CC BY-NC 4.0 (non-commercial).")


if __name__ == "__main__":
    main()
