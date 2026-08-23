"""Which source to believe per signal, and why two devices are not ranked.

`WellnessSample` is keyed (user, date, source), so several sources reporting one day is the
designed shape. Nothing read `source`: readiness took a single row ordered by `created_at`,
so whichever landed last won and the other row's signals were dropped.

The model is objective-vs-subjective, not a league table of providers.
"""

from datetime import UTC, datetime, timedelta

from app.logic.wellness_source_authority import (
    MANUAL_SOURCE,
    OBJECTIVE_SIGNALS,
    SUBJECTIVE_SIGNALS,
    SignalCandidate,
    authority_rank,
    is_device_source,
    resolve_signal_source,
)

_T = datetime(2026, 8, 23, 6, 0, tzinfo=UTC)


# ── who counts as a device ────────────────────────────────────────────────────


def test_anything_that_is_not_manual_is_a_device() -> None:
    """Not a list of provider names: a new integration must need no edit here."""
    assert is_device_source("oura")
    assert is_device_source("garmin")
    assert is_device_source("some_provider_that_does_not_exist_yet")
    assert not is_device_source(MANUAL_SOURCE)


def test_manual_is_recognised_regardless_of_casing_or_padding() -> None:
    assert not is_device_source("Manual")
    assert not is_device_source("  manual  ")


# ── authority inverts by signal ───────────────────────────────────────────────


def test_a_device_outranks_the_athlete_on_measured_signals() -> None:
    """A wearable measures HRV better than a person estimating it."""
    for signal in OBJECTIVE_SIGNALS:
        assert authority_rank(signal, "oura") > authority_rank(signal, MANUAL_SOURCE), signal


def test_the_athlete_outranks_a_device_on_felt_signals() -> None:
    """Soreness, mood and stress are not measurable by a device at all.

    A provider emitting them is inferring; the athlete is the primary instrument.
    """
    for signal in SUBJECTIVE_SIGNALS:
        assert authority_rank(signal, MANUAL_SOURCE) > authority_rank(signal, "oura"), signal


def test_a_device_reported_subjective_signal_is_still_evidence() -> None:
    """Weaker than the athlete's own report, but not discarded.

    Inverting the ranking rather than excluding devices means a provider-derived stress
    score still counts when the athlete reported nothing.
    """
    chosen = resolve_signal_source("stress", [SignalCandidate("oura", 7.0, ingested_at=_T)])

    assert chosen == ("oura", 7.0)


def test_two_devices_are_not_ranked_against_each_other() -> None:
    """There is no evidence here that one wearable measures HRV better than another.

    Inventing an order would be exactly the unbacked claim this path is being cleaned of.
    """
    assert authority_rank("hrv_ms", "oura") == authority_rank("hrv_ms", "garmin")


def test_equal_authority_falls_back_to_ingestion_recency() -> None:
    """The previous behaviour, narrowed to where it is actually defensible."""
    chosen = resolve_signal_source(
        "hrv_ms",
        [
            SignalCandidate("oura", 50.0, ingested_at=_T),
            SignalCandidate("garmin", 62.0, ingested_at=_T + timedelta(hours=1)),
        ],
    )

    assert chosen == ("garmin", 62.0)


# ── a source that reported nothing is not a candidate ─────────────────────────


def test_a_higher_authority_source_that_reported_nothing_does_not_win() -> None:
    """The bug this exists to stop: authority must not beat actually having the reading.

    An Oura sync that carried no soreness must not suppress the athlete's soreness, and a
    manual check-in with no HRV must not suppress the device's HRV.
    """
    assert resolve_signal_source(
        "hrv_ms",
        [SignalCandidate("oura", None, ingested_at=_T), SignalCandidate(MANUAL_SOURCE, 58.0, ingested_at=_T)],
    ) == (MANUAL_SOURCE, 58.0)

    assert resolve_signal_source(
        "soreness",
        [SignalCandidate(MANUAL_SOURCE, None, ingested_at=_T), SignalCandidate("oura", 4.0, ingested_at=_T)],
    ) == ("oura", 4.0)


def test_no_source_supplying_it_stays_missing() -> None:
    """Missing stays missing — it does not become a number."""
    assert resolve_signal_source("hrv_ms", []) is None
    assert resolve_signal_source("hrv_ms", [SignalCandidate("oura", None, ingested_at=_T)]) is None


def test_a_legacy_row_with_no_ingest_time_does_not_raise() -> None:
    """Sorting must not compare None against a datetime."""
    chosen = resolve_signal_source(
        "hrv_ms",
        [SignalCandidate("oura", 55.0), SignalCandidate("garmin", 60.0, ingested_at=_T)],
    )

    assert chosen == ("garmin", 60.0)


def test_only_legacy_rows_still_resolve() -> None:
    chosen = resolve_signal_source("hrv_ms", [SignalCandidate("oura", 55.0)])

    assert chosen == ("oura", 55.0)


# ── the two families cover every configured signal ────────────────────────────


def test_every_configured_signal_is_classified() -> None:
    """An unclassified signal would silently default to the objective ordering."""
    from app.logic.wellness_signals import SIGNAL_CONFIG

    assert set(SIGNAL_CONFIG) == OBJECTIVE_SIGNALS | SUBJECTIVE_SIGNALS
    assert not (OBJECTIVE_SIGNALS & SUBJECTIVE_SIGNALS)


# ── quality and measurement time actually decide ties ─────────────────────────


def test_a_provider_flagged_degraded_reading_loses_to_an_unflagged_one() -> None:
    """This is what stops `quality` being a decorative column.

    Oura reports `low_battery_alert`; a night it flagged is materially less reliable than
    one it did not flag, and both are device readings of equal authority.
    """
    chosen = resolve_signal_source(
        "hrv_ms",
        [
            SignalCandidate("oura", 40.0, quality=0.5, ingested_at=_T + timedelta(hours=2)),
            SignalCandidate("garmin", 66.0, ingested_at=_T),
        ],
    )

    assert chosen == ("garmin", 66.0)


def test_unreported_quality_is_not_treated_as_a_defect() -> None:
    """A source saying nothing about quality must not lose to one that says 0.9.

    "No problem reported" is compared as unflagged, which is a comparison — the row still
    stores NULL, because it is not a claim the reading was perfect.
    """
    chosen = resolve_signal_source(
        "hrv_ms",
        [
            SignalCandidate("oura", 55.0, quality=0.9, ingested_at=_T),
            SignalCandidate("garmin", 61.0, ingested_at=_T),
        ],
    )

    assert chosen == ("garmin", 61.0)


def test_authority_still_outranks_quality() -> None:
    """Precedence is strict: a flagged manual soreness still beats a pristine device one."""
    chosen = resolve_signal_source(
        "soreness",
        [
            SignalCandidate(MANUAL_SOURCE, 7.0, quality=0.5, ingested_at=_T),
            SignalCandidate("oura", 2.0, quality=1.0, ingested_at=_T + timedelta(hours=3)),
        ],
    )

    assert chosen == (MANUAL_SOURCE, 7.0)


def test_measurement_time_beats_upload_time_for_recency() -> None:
    """Between two devices, the later MEASUREMENT is the more current reading.

    The later upload may just be a slower sync, which is what ingestion time was really
    measuring before.
    """
    chosen = resolve_signal_source(
        "hrv_ms",
        [
            SignalCandidate(
                "oura", 50.0,
                measured_at=_T + timedelta(hours=5),
                ingested_at=_T,                       # measured late, uploaded early
            ),
            SignalCandidate(
                "garmin", 62.0,
                measured_at=_T,
                ingested_at=_T + timedelta(hours=9),  # measured early, uploaded late
            ),
        ],
    )

    assert chosen == ("oura", 50.0)


def test_ingestion_time_is_used_when_no_measurement_time_exists() -> None:
    """Rows written before this feature keep working on the old signal."""
    chosen = resolve_signal_source(
        "hrv_ms",
        [
            SignalCandidate("oura", 50.0, ingested_at=_T),
            SignalCandidate("garmin", 62.0, ingested_at=_T + timedelta(hours=1)),
        ],
    )

    assert chosen == ("garmin", 62.0)


def test_an_undated_row_can_still_win_on_authority() -> None:
    """Having no timestamp must not silently demote a more authoritative source."""
    chosen = resolve_signal_source(
        "soreness",
        [
            SignalCandidate(MANUAL_SOURCE, 8.0),  # no timestamps at all
            SignalCandidate("oura", 1.0, ingested_at=_T),
        ],
    )

    assert chosen == (MANUAL_SOURCE, 8.0)


def test_an_undated_row_can_still_win_on_quality() -> None:
    chosen = resolve_signal_source(
        "hrv_ms",
        [
            SignalCandidate("garmin", 70.0),                      # unflagged, undated
            SignalCandidate("oura", 40.0, quality=0.5, ingested_at=_T),
        ],
    )

    assert chosen == ("garmin", 70.0)
