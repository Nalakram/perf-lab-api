"""Load the ScopeSense lifelogging dataset — the first real HRV source in this repo.

ScopeSense (Simula, https://osf.io/v5acr/) is 255 days of two participants logging PMSys
wellness and training alongside an Apple Watch. It is not on Kaggle, so unlike the other
corpora it is fetched by hand and unpacked under ``data/scopesense/``.

WHY IT IS HERE. PMData gave real subjective signal but no HRV — its Fitbit Versa 2 does not
expose it. Every ``hrv_ms`` value this system has ever seen came from a CSV that declares
itself synthetic (``app/ml/q2_recovery/model_card.py:26-31``) or from a bodyweight formula in
a seeder. ScopeSense ships ``HKQuantityTypeIdentifierHeartRateVariabilitySDNN``, which is a
real measurement from a real wrist.

THE METRIC IS SDNN, AND THAT IS THE WHOLE POINT. HealthKit exposes only SDNN; Oura, Whoop and
Garmin report rMSSD, and SDNN runs 10-25% higher on the same inter-beat intervals. This loader
therefore stamps ``hrv_metric="sdnn"`` on every reading so ``readiness_service._baselines``
never averages it against rMSSD history. Feeding SDNN into a field documented as "rMSSD-style"
without saying so would have biased every baseline and z-score silently — see migration
``a040_wellness_hrv_metric``.

FORMAT DIFFERS FROM PMDATA despite both coming from PMSys: semicolon-delimited, European
decimal commas, ``DD.MM.YYYY`` dates, a UTF-8 BOM, capitalized column names, and a
``training.csv`` of pre-computed daily load rather than PMData's per-session ``srpe.csv``.
So this is its own reader, not a parameterization of ``load_pmdata``.

SCALE DIRECTION is the same as PMData's and is verified independently here. ScopeSense has no
``soreness_area`` column, so the PMData evidence does not transfer. Instead every 1-5 item is
correlated against ``Readiness`` — which the dataset documents as 0-10 higher-is-better:
Fatigue r=+0.27, Soreness r=+0.34, Mood r=+0.34, Stress r=+0.27, SleepQuality r=+0.29 across
all 492 answered rows. All positive, so higher = better throughout, and soreness/stress invert
into this system's higher-is-worse 0-10 while mood only rescales.

HRV IS A DAILY MEAN, WHICH IS A DERIVATION. The watch records SDNN sporadically (~80k readings
for participant A), while this system stores one wellness value per day. The mean of a day's
readings is taken, and the reading count is preserved in ``raw`` so a consumer can judge how
much it rests on. It mixes daytime and overnight readings, unlike the overnight-only
convention most HRV guidance assumes; that limitation is real and is not papered over.

Run (prints a summary, writes nothing):
    python -m app.scripts.load_scopesense
"""

from __future__ import annotations

import argparse
import csv
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date as date_cls
from datetime import datetime
from pathlib import Path
from typing import Any

from app.integrations.base import NormalizedWellness

_ROOT = Path("data/scopesense")

SOURCE = "scopesense"

#: HealthKit exposes only SDNN. Declared, never assumed — see module docstring.
HRV_METRIC = "sdnn"

#: PMSys 1-5 Likert, higher = better. Anything outside is not an answer.
_LIKERT_LO, _LIKERT_HI = 1.0, 5.0


@dataclass
class ScopeSenseSession:
    """One training day. ScopeSense records daily load, not per-session rows."""

    day: date_cls
    session_rpe: float
    duration_minutes: float
    raw: dict[str, Any] = field(default_factory=dict)


def _root(root: Path | None = None) -> Path:
    base = root or _ROOT
    if not base.is_dir() or not any(base.glob("*/PMSys/wellness.csv")):
        raise SystemExit(
            f"ScopeSense not found under {base}/. It is OSF-hosted, not Kaggle: download "
            "https://osf.io/v5acr/ and unpack the participant folders there."
        )
    return base


def participants(root: Path | None = None) -> list[str]:
    base = _root(root)
    return sorted(p.name for p in base.glob("*") if (p / "PMSys" / "wellness.csv").is_file())


def _num(value: str | None) -> float | None:
    """Parse a European-decimal number. Blank or unparseable is absent, never zero."""
    if value is None:
        return None
    text = value.strip().replace(",", ".")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _likert(value: str | None) -> float | None:
    parsed = _num(value)
    if parsed is None or not (_LIKERT_LO <= parsed <= _LIKERT_HI):
        return None
    return parsed


def _invert_to_ten(value: float | None) -> float | None:
    """PMSys 1-5 higher-is-better -> this system's 0-10 higher-is-WORSE."""
    return None if value is None else round((_LIKERT_HI - value) * 2.5, 2)


def _rescale_to_ten(value: float | None) -> float | None:
    return None if value is None else round((value - _LIKERT_LO) * 2.5, 2)


def _rescale_to_hundred(value: float | None) -> float | None:
    return None if value is None else round((value - _LIKERT_LO) * 25.0, 2)


def _ddmmyyyy(value: str) -> date_cls | None:
    text = (value or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%d.%m.%Y").date()
    except ValueError:
        return None


def _healthkit_day(value: str) -> date_cls | None:
    """HealthKit stamps '2021-02-08 00:25:05 +0200'. The calendar day is what we key on."""
    text = (value or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text[:19], "%Y-%m-%d %H:%M:%S").date()
    except ValueError:
        return None


def _daily_mean_healthkit(path: Path) -> dict[date_cls, tuple[float, int]]:
    """Mean of a day's readings, plus how many there were. Empty when the file is absent."""
    if not path.is_file():
        return {}
    buckets: dict[date_cls, list[float]] = defaultdict(list)
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            day = _healthkit_day(row.get("startDate", ""))
            value = _num(row.get("value"))
            if day is not None and value is not None and value > 0:
                buckets[day].append(value)
    return {d: (round(statistics.mean(v), 2), len(v)) for d, v in buckets.items()}


def load_wellness(participant: str, root: Path | None = None) -> list[NormalizedWellness]:
    """One participant's daily check-ins, joined to that day's Apple Watch measurements."""
    base = _root(root)
    path = base / participant / "PMSys" / "wellness.csv"
    if not path.is_file():
        return []

    watch = base / participant / "Apple watch"
    hrv = _daily_mean_healthkit(watch / "HKQuantityTypeIdentifierHeartRateVariabilitySDNN.csv")
    rhr = _daily_mean_healthkit(watch / "HKQuantityTypeIdentifierRestingHeartRate.csv")

    out: list[NormalizedWellness] = []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle, delimiter=";"):
            day = _ddmmyyyy(row.get("Date", ""))
            if day is None:
                continue

            hrv_value, hrv_n = hrv.get(day, (None, 0))
            rhr_value, _ = rhr.get(day, (None, 0))

            raw: dict[str, Any] = {
                "dataset": "osf:v5acr scopesense",
                "participant": participant,
                # No field in this vocabulary; kept rather than dropped.
                "pmsys_fatigue_1_5": _likert(row.get("Fatigue")),
                "pmsys_readiness_0_10": _num(row.get("Readiness")),
                "pmsys_soreness_1_5": _likert(row.get("Soreness")),
            }
            if hrv_n:
                # How many watch readings the daily mean rests on — a one-reading day and a
                # two-hundred-reading day are not equally trustworthy.
                raw["hrv_reading_count"] = hrv_n

            out.append(
                NormalizedWellness(
                    day=day,
                    hrv_ms=hrv_value,
                    # Declared, never assumed: HealthKit exposes only SDNN.
                    hrv_metric=HRV_METRIC if hrv_value is not None else None,
                    sleep_hours=_num(row.get("SleepDurH")),
                    sleep_quality=_rescale_to_hundred(_likert(row.get("SleepQuality"))),
                    resting_hr=rhr_value,
                    soreness=_invert_to_ten(_likert(row.get("Soreness"))),
                    mood=_rescale_to_ten(_likert(row.get("Mood"))),
                    stress=_invert_to_ten(_likert(row.get("Stress"))),
                    measured_at=None,  # PMSys records only the calendar day here
                    quality=None,  # neither source reports a reliability signal
                    raw=raw,
                )
            )
    return out


def load_sessions(participant: str, root: Path | None = None) -> list[ScopeSenseSession]:
    """One participant's training days.

    ``training.csv`` is a daily-load table: one row per day carrying that day's RPE and
    duration alongside pre-computed ATL/monotony/strain figures this system computes itself
    and therefore ignores. Rows with no RPE are skipped rather than defaulted — ``session_rpe``
    is required and unanswered is not zero.
    """
    base = _root(root)
    path = base / participant / "PMSys" / "training.csv"
    if not path.is_file():
        return []

    out: list[ScopeSenseSession] = []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle, delimiter=";"):
            day = _ddmmyyyy(row.get("Date", ""))
            rpe = _num(row.get("RPE"))
            duration = _num(row.get("Duration [min]"))
            if day is None or rpe is None or duration is None:
                continue
            if not (1.0 <= rpe <= 10.0) or duration <= 0:
                continue
            out.append(
                ScopeSenseSession(
                    day=day,
                    session_rpe=rpe,
                    duration_minutes=duration,
                    raw={
                        "dataset": "osf:v5acr scopesense",
                        "participant": participant,
                        "daily_load_srpe": _num(row.get("SRPE")),
                    },
                )
            )
    out.sort(key=lambda s: s.day)
    return out


def main() -> None:
    argparse.ArgumentParser(description="Summarize the ScopeSense corpus (reads only)").parse_args()

    base = _root()
    names = participants(base)
    total_w = total_s = with_hrv = with_soreness = 0
    for name in names:
        wellness = load_wellness(name, base)
        sessions = load_sessions(name, base)
        hrv_days = sum(1 for w in wellness if w.hrv_ms is not None)
        sore = sum(1 for w in wellness if w.soreness is not None)
        total_w += len(wellness)
        total_s += len(sessions)
        with_hrv += hrv_days
        with_soreness += sore
        print(
            f"  {name}: {len(wellness):4d} check-ins ({sore} with soreness, "
            f"{hrv_days} with SDNN HRV), {len(sessions):3d} training days"
        )

    print(
        f"\n{len(names)} participant(s): {total_w} check-ins, {with_soreness} with soreness, "
        f"{with_hrv} with real HRV, {total_s} training days with real RPE."
    )
    print(f"HRV metric declared as '{HRV_METRIC}' — never pooled with rMSSD history.")


if __name__ == "__main__":
    main()
