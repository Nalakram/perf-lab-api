"""The PMData loader maps PMSys scales onto this system's vocabulary in the right direction.

This is the file that matters most about PMData, because the failure it guards is silent.
PMSys scores soreness and stress 1-5 where **higher is better**; this system stores them
0-10 where **higher is worse**. Get that backwards and nothing errors — the EKF simply
assimilates the sign-flipped signal, the calibration gate reports a plausible-looking
number, and the twin learns that sore athletes are fresh.

The direction is not a matter of taste. In the real corpus, ``soreness_area`` — the body
region the participant tagged — is named on 100% of rows scoring 1 and 89% scoring 2,
versus 0.1% at 3 and 0% at 4-5. Low score = actually sore. ``test_real_corpus_*`` below
re-derives that from the shipped data when it is present.

The hermetic tests build a tiny fixture rather than depending on the 3 GB download, so
they run in CI; the corpus-backed ones skip when it is absent.
"""
from __future__ import annotations

import csv
from pathlib import Path

import pytest

from app.scripts import load_pmdata

_WELLNESS_HEADER = [
    "effective_time_frame", "fatigue", "mood", "readiness",
    "sleep_duration_h", "sleep_quality", "soreness", "soreness_area", "stress",
]
_SRPE_HEADER = ["end_date_time", "activity_names", "perceived_exertion", "duration_min"]


def _write(root: Path, participant: str, wellness: list[list], srpe: list[list]) -> None:
    pmsys = root / participant / "pmsys"
    pmsys.mkdir(parents=True, exist_ok=True)
    with (pmsys / "wellness.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(_WELLNESS_HEADER)
        w.writerows(wellness)
    with (pmsys / "srpe.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(_SRPE_HEADER)
        w.writerows(srpe)


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    """Two days at the extremes of the PMSys scale, plus one unanswered row."""
    _write(
        tmp_path,
        "p01",
        wellness=[
            # worst possible day: soreness=1 (very sore), stress=1, mood=1
            ["2019-11-01T08:00:00.000Z", 1, 1, 0, 6.0, 1, 1, "[12921003]", 1],
            # best possible day: soreness=5 (no soreness), stress=5, mood=5
            ["2019-11-02T08:00:00.000Z", 5, 5, 10, 8.0, 5, 5, "[]", 5],
            # unanswered: 0 is outside the documented 1-5 scale
            ["2019-11-03T08:00:00.000Z", 0, 0, 0, 0, 0, 0, "[]", 0],
        ],
        srpe=[
            ["2019-11-02T20:00:00.000Z", "['individual', 'running']", 7, 45],
            ["2019-11-02T21:00:00.000Z", "['individual', 'strength']", 9, 60],
            ["2019-11-04T20:00:00.000Z", "['individual', 'strength', 'running']", 5, 90],
            # no RPE logged — session_rpe is required, so this must be dropped, not defaulted
            ["2019-11-05T20:00:00.000Z", "['individual', 'running']", "", ""],
        ],
    )
    return tmp_path


def test_soreness_and_stress_are_inverted(corpus: Path) -> None:
    """PMSys higher-is-better becomes this system's higher-is-worse."""
    readings = load_pmdata.load_wellness("p01", corpus)
    worst, best = readings[0], readings[1]

    # soreness=1 in PMSys means "very sore" -> the WORST score here, 10.
    assert worst.soreness == 10.0, "PMSys soreness=1 (very sore) must map to 10 (worst)"
    assert best.soreness == 0.0, "PMSys soreness=5 (no soreness) must map to 0 (best)"
    assert worst.stress == 10.0
    assert best.stress == 0.0


def test_mood_keeps_its_direction(corpus: Path) -> None:
    """mood is higher-is-better on BOTH sides, so it is rescaled but never flipped."""
    worst, best = load_pmdata.load_wellness("p01", corpus)[:2]
    assert worst.mood == 0.0, "PMSys mood=1 (bad mood) must stay the low end"
    assert best.mood == 10.0
    # The distinguishing assertion: mood and soreness move in OPPOSITE directions for the
    # same underlying "good day". If someone applies one rule to both, this fails.
    assert best.mood > worst.mood
    assert best.soreness < worst.soreness


def test_sleep_quality_rescales_to_hundred(corpus: Path) -> None:
    worst, best = load_pmdata.load_wellness("p01", corpus)[:2]
    assert worst.sleep_quality == 0.0
    assert best.sleep_quality == 100.0
    assert best.sleep_hours == 8.0


def test_zero_is_unanswered_not_worst(corpus: Path) -> None:
    """A 0 is outside the 1-5 scale: nobody answered. It must not become a score."""
    unanswered = load_pmdata.load_wellness("p01", corpus)[2]
    assert unanswered.soreness is None, "0 must be missing, not the worst-possible soreness"
    assert unanswered.stress is None
    assert unanswered.mood is None
    assert unanswered.sleep_quality is None
    assert unanswered.sleep_hours is None


def test_unmeasured_signals_stay_none(corpus: Path) -> None:
    """PMData's Fitbit Versa 2 exposes no rMSSD, and resting HR is not in wellness.csv."""
    reading = load_pmdata.load_wellness("p01", corpus)[0]
    assert reading.hrv_ms is None
    assert reading.resting_hr is None
    assert reading.quality is None, "PMSys reports no reliability signal; none may be invented"


def test_fatigue_and_readiness_are_preserved_not_dropped(corpus: Path) -> None:
    """Neither has a field in this vocabulary, so they live in raw rather than vanishing."""
    reading = load_pmdata.load_wellness("p01", corpus)[0]
    assert reading.raw["pmsys_fatigue_1_5"] == 1.0
    assert reading.raw["soreness_area"] == "[12921003]"
    assert reading.raw["participant"] == "p01"


def test_session_rpe_passes_through_unscaled(corpus: Path) -> None:
    """perceived_exertion is already Borg CR-10, which is session_rpe's own domain."""
    sessions = load_pmdata.load_sessions("p01", corpus)
    assert [s.session_rpe for s in sessions] == [7.0, 9.0, 5.0]
    assert [s.duration_minutes for s in sessions] == [45.0, 60.0, 90.0]


def test_session_without_rpe_is_dropped_not_defaulted(corpus: Path) -> None:
    sessions = load_pmdata.load_sessions("p01", corpus)
    assert len(sessions) == 3, "the row with no perceived_exertion must not be invented into one"


def test_modality_mixes_rather_than_picking_first_tag(corpus: Path) -> None:
    sessions = load_pmdata.load_sessions("p01", corpus)
    assert sessions[0].modality == "Running"
    assert sessions[1].modality == "Strength"
    # strength + running: neither tag wins arbitrarily.
    assert sessions[2].modality == "Mixed"


# --- corpus-backed: re-derive the direction from the shipped data ---------------------

def _corpus_present() -> bool:
    try:
        return bool(load_pmdata.participants())
    except SystemExit:
        return False


@pytest.mark.skipif(not _corpus_present(), reason="PMData not downloaded")
def test_real_corpus_confirms_low_score_means_sore() -> None:
    """The evidence the inversion rests on, re-checked against the real corpus.

    A named body region is the participant telling us they are sore. If that correlates
    with LOW PMSys scores, higher-is-better holds and the inversion is right.
    """
    named_by_score: dict[float, list[int]] = {}
    for participant in load_pmdata.participants():
        for reading in load_pmdata.load_wellness(participant):
            raw_score = reading.raw.get("pmsys_soreness_1_5")
            if raw_score is None:
                continue
            slot = named_by_score.setdefault(raw_score, [0, 0])
            slot[0 if "soreness_area" in reading.raw else 1] += 1

    def pct_named(score: float) -> float:
        named, unnamed = named_by_score.get(score, [0, 0])
        return 100.0 * named / (named + unnamed) if (named + unnamed) else 0.0

    assert pct_named(1.0) > 90.0, "score 1 should almost always name a sore area"
    assert pct_named(5.0) < 5.0, "score 5 should almost never name a sore area"
    assert pct_named(1.0) > pct_named(5.0)


@pytest.mark.skipif(not _corpus_present(), reason="PMData not downloaded")
def test_real_corpus_shape_matches_the_published_figures() -> None:
    """1,747 check-ins and 783 sessions are the dataset's own published counts."""
    participants = load_pmdata.participants()
    assert len(participants) == 16

    checkins = sum(len(load_pmdata.load_wellness(p)) for p in participants)
    assert checkins == 1747

    # 772, not 783: p16 logged 11 sessions with no perceived_exertion at all.
    sessions = sum(len(load_pmdata.load_sessions(p)) for p in participants)
    assert sessions == 772

    for participant in participants:
        for reading in load_pmdata.load_wellness(participant):
            if reading.soreness is not None:
                assert 0.0 <= reading.soreness <= 10.0
            if reading.stress is not None:
                assert 0.0 <= reading.stress <= 10.0
