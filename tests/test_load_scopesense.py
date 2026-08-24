"""The ScopeSense loader declares its HRV metric and inverts the PMSys scales correctly.

ScopeSense is the first source in this repo carrying a real measured HRV series. That makes
one assertion load-bearing above all others: the reading must be stamped ``sdnn``. HealthKit
exposes only SDNN, `hrv_ms` is documented as "rMSSD-style", and SDNN runs 10-25% higher on the
same inter-beat intervals — so an unlabelled reading would be averaged into rMSSD baselines and
silently bias every z-score. Migration a040 exists for this; the loader must actually use it.

The scale direction is the same as PMData's but the evidence is not: ScopeSense has no
``soreness_area`` column, so it was re-derived by correlating every 1-5 item against
``Readiness`` (documented 0-10, higher = more ready) across all 492 answered rows. All five
correlated positively (+0.27 to +0.34), so higher = better throughout.

Format traps this pins, all of which silently produce garbage rather than errors: a
semicolon delimiter, European decimal commas, ``DD.MM.YYYY`` dates, and a UTF-8 BOM on the
first header cell.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from app.scripts import load_scopesense

_W_HEADER = "Date;Fatigue;Soreness;Mood;Stress;SleepQuality;SleepDurH;Readiness"
_T_HEADER = "Date;Daily Load;SRPE;RPE;Duration [min];ATL;Weekly Load;Monotony;Strain;Acwr;Ctl28;Ctl42;;"


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    p = tmp_path / "Participant A"
    (p / "PMSys").mkdir(parents=True)
    (p / "Apple watch").mkdir(parents=True)

    # BOM on the first cell, exactly as the real export ships it.
    (p / "PMSys" / "wellness.csv").write_text(
        "﻿" + _W_HEADER + "\n"
        "08.02.2021;1;1;1;1;1;6;1\n"      # worst day at the bottom of every scale
        "09.02.2021;5;5;5;5;5;8;9\n"      # best day
        "10.02.2021;3;0;3;3;3;7;5\n",     # soreness unanswered (0 is outside 1-5)
        encoding="utf-8",
    )
    (p / "PMSys" / "training.csv").write_text(
        "﻿" + _T_HEADER + "\n"
        ";;;;;;;;;;;;;\n"                                  # the blank spacer row
        "08.02.2021;120;120;6;20;17,14;120;0,41;49,2;0,17;4,29;2,86;;\n"
        "09.02.2021;;;;;;;;;;;;;\n",                       # a day with no RPE logged
        encoding="utf-8",
    )
    (p / "Apple watch" / "HKQuantityTypeIdentifierHeartRateVariabilitySDNN.csv").write_text(
        "Type,creationDate,startDate,endDate,sourceName,value,bpm,time\n"
        "X,2021-02-08 00:25:05 +0200,2021-02-08 00:24:00 +0200,x,Apple Watch,40.0,59,x\n"
        "X,2021-02-08 03:25:05 +0200,2021-02-08 03:24:00 +0200,x,Apple Watch,50.0,59,x\n"
        "X,2021-02-09 01:25:05 +0200,2021-02-09 01:24:00 +0200,x,Apple Watch,70.0,59,x\n",
        encoding="utf-8",
    )
    (p / "Apple watch" / "HKQuantityTypeIdentifierRestingHeartRate.csv").write_text(
        "Type,creationDate,startDate,endDate,sourceName,value,unit\n"
        "X,2021-02-08 20:40:03 +0200,2021-02-08 01:04:37 +0200,x,Apple Watch,63,count/min\n",
        encoding="utf-8",
    )
    return tmp_path


def test_hrv_is_always_declared_sdnn(corpus: Path) -> None:
    """The assertion this dataset exists for. An unlabelled reading pollutes rMSSD baselines."""
    readings = load_scopesense.load_wellness("Participant A", corpus)
    with_hrv = [r for r in readings if r.hrv_ms is not None]

    assert with_hrv, "fixture must produce at least one HRV reading"
    assert all(r.hrv_metric == "sdnn" for r in with_hrv)


def test_a_day_without_watch_data_declares_no_metric(corpus: Path) -> None:
    """No reading means no metric — not a metric attached to a missing value."""
    third = load_scopesense.load_wellness("Participant A", corpus)[2]
    assert third.hrv_ms is None
    assert third.hrv_metric is None


def test_hrv_is_the_daily_mean_and_says_how_many_readings(corpus: Path) -> None:
    """The mean is a derivation, so the count it rests on travels with it."""
    first, second, _ = load_scopesense.load_wellness("Participant A", corpus)
    assert first.hrv_ms == 45.0  # mean of 40 and 50
    assert first.raw["hrv_reading_count"] == 2
    assert second.hrv_ms == 70.0
    assert second.raw["hrv_reading_count"] == 1


def test_soreness_and_stress_invert_while_mood_does_not(corpus: Path) -> None:
    """Same rule as PMData, re-derived here from the Readiness correlation."""
    worst, best, _ = load_scopesense.load_wellness("Participant A", corpus)

    assert worst.soreness == 10.0 and best.soreness == 0.0
    assert worst.stress == 10.0 and best.stress == 0.0
    assert worst.mood == 0.0 and best.mood == 10.0
    # The distinguishing check: for the same "good day" these move in OPPOSITE directions.
    assert best.mood > worst.mood and best.soreness < worst.soreness


def test_zero_is_unanswered_not_worst(corpus: Path) -> None:
    third = load_scopesense.load_wellness("Participant A", corpus)[2]
    assert third.soreness is None, "0 is outside the 1-5 scale — nobody answered"


def test_scales_and_dates_parse(corpus: Path) -> None:
    worst, best, _ = load_scopesense.load_wellness("Participant A", corpus)
    assert worst.day == date(2021, 2, 8), "DD.MM.YYYY, not MM/DD or ISO"
    assert worst.sleep_quality == 0.0 and best.sleep_quality == 100.0
    assert worst.sleep_hours == 6.0
    assert worst.resting_hr == 63.0


def test_training_rows_need_a_real_rpe(corpus: Path) -> None:
    """The blank spacer row and the no-RPE day are skipped, not defaulted to zero."""
    sessions = load_scopesense.load_sessions("Participant A", corpus)
    assert len(sessions) == 1
    assert sessions[0].session_rpe == 6.0
    assert sessions[0].duration_minutes == 20.0
    assert sessions[0].day == date(2021, 2, 8)


def test_european_decimals_parse(corpus: Path) -> None:
    """`17,14` is 17.14, not 1714 and not a parse failure that silently drops the row."""
    assert load_scopesense._num("17,14") == 17.14
    assert load_scopesense._num("0,41") == 0.41
    assert load_scopesense._num("") is None
    assert load_scopesense._num("n/a") is None


def test_a_missing_corpus_fails_loudly(tmp_path: Path) -> None:
    """It is OSF-hosted, so the error must say where to get it rather than return empty."""
    with pytest.raises(SystemExit) as excinfo:
        load_scopesense.participants(tmp_path)
    assert "osf.io/v5acr" in str(excinfo.value)
