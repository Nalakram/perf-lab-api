"""An HRV baseline may only average like against like — same source AND same metric.

`hrv_ms` stores a number but not which HRV metric produced it, and devices disagree: Oura,
Whoop and Garmin report rMSSD; Apple Watch reports SDNN, and HealthKit exposes no other. SDNN
runs 10-25% higher than rMSSD computed from the same inter-beat intervals, so the two are not
interchangeable.

That makes pooling them a units bug with no symptom. `wellness_modifier` z-scores today's
value against the 28-day mean using an anchor of 60.0 ms tuned for rMSSD, so an SDNN reading
scored against an rMSSD baseline moves readiness on an instrument change the athlete never
made. PR #211 fixed exactly this shape for `source`; this is the same defect one level down.

The rule is fail-closed in both directions: a declared metric matches only history declaring
the same one, and an undeclared (NULL) reading matches only other undeclared rows. Unknown is
never treated as "assumed rMSSD".
"""

from datetime import UTC, datetime, timedelta
from datetime import date as date_cls

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.user import User
from app.models.wellness import WellnessSample
from app.services.readiness_service import _baselines, _resolve_day

_TODAY = date_cls(2026, 8, 24)


async def _user(db, email: str) -> User:
    u = User(email=email, hashed_password="x", is_active=True)
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


async def _sample(db, user_id: int, on: date_cls, source: str, **signals) -> WellnessSample:
    row = WellnessSample(
        user_id=user_id,
        date=on,
        source=source,
        created_at=datetime(2026, 8, 24, 6, 0, tzinfo=UTC).replace(tzinfo=None),
        **signals,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def test_an_sdnn_history_never_enters_an_rmssd_baseline(async_db) -> None:
    """The bug in the shape it actually occurs: one athlete, two devices, two metrics.

    Ten days of Apple Watch SDNN around 70, then an Oura ring reporting rMSSD around 50.
    Pooling puts the baseline near 60 and reports the athlete as well BELOW their norm on day
    one of the new ring — an artefact of the metric change, not a loss of recovery.
    """
    user = await _user(async_db, "hrvm-mixed@test.com")
    uid = user.id
    for i in range(1, 11):
        await _sample(
            async_db, uid, _TODAY - timedelta(days=i), "apple_watch",
            hrv_ms=70.0, hrv_metric="sdnn",
        )
    for i in range(1, 4):
        await _sample(
            async_db, uid, _TODAY - timedelta(days=i), "oura",
            hrv_ms=50.0, hrv_metric="rmssd",
        )

    per_source_only = await _baselines(
        async_db, uid, before=_TODAY, source_by_signal={"hrv_ms": "oura"}
    )
    like_for_like = await _baselines(
        async_db,
        uid,
        before=_TODAY,
        source_by_signal={"hrv_ms": "oura"},
        metric_by_signal={"hrv_ms": "rmssd"},
    )

    # Source alone already isolates Oura here, so the distinguishing case is below — but pin
    # this so the two filters are known to compose rather than one masking the other.
    assert per_source_only["hrv_ms"] == 50.0
    assert like_for_like["hrv_ms"] == 50.0


async def test_metric_filter_bites_even_when_the_source_is_identical(async_db) -> None:
    """The case `source` alone cannot catch: one source, two metrics.

    A phone app that changes what it reports — or a provider that starts writing SDNN into
    the same slot — keeps its source string. Only the metric distinguishes the readings, so
    this is the assertion that proves the new filter does real work.
    """
    user = await _user(async_db, "hrvm-samesource@test.com")
    uid = user.id
    for i in range(1, 11):
        await _sample(
            async_db, uid, _TODAY - timedelta(days=i), "healthkit",
            hrv_ms=70.0, hrv_metric="sdnn",
        )
    for i in range(11, 15):
        await _sample(
            async_db, uid, _TODAY - timedelta(days=i), "healthkit",
            hrv_ms=50.0, hrv_metric="rmssd",
        )

    pooled = await _baselines(
        async_db, uid, before=_TODAY, source_by_signal={"hrv_ms": "healthkit"}
    )
    rmssd_only = await _baselines(
        async_db,
        uid,
        before=_TODAY,
        source_by_signal={"hrv_ms": "healthkit"},
        metric_by_signal={"hrv_ms": "rmssd"},
    )

    assert pooled["hrv_ms"] is not None and 50.0 < pooled["hrv_ms"] < 70.0, (
        "source-only filtering pools both metrics — this is the defect"
    )
    assert rmssd_only["hrv_ms"] == 50.0, "the rMSSD baseline must contain only rMSSD history"


async def test_a_new_metric_restarts_the_baseline_rather_than_borrowing_one(async_db) -> None:
    """Switching instrument costs the personal baseline, exactly as switching provider does.

    The new metric's offset for this athlete is genuinely unknown, so the caller falls back
    to the population anchor. Reusing the old metric's mean would be the imputation defect
    wearing a different hat.
    """
    user = await _user(async_db, "hrvm-newmetric@test.com")
    uid = user.id
    for i in range(1, 15):
        await _sample(
            async_db, uid, _TODAY - timedelta(days=i), "oura",
            hrv_ms=50.0, hrv_metric="rmssd",
        )

    switched = await _baselines(
        async_db,
        uid,
        before=_TODAY,
        source_by_signal={"hrv_ms": "oura"},
        metric_by_signal={"hrv_ms": "sdnn"},
    )

    assert switched["hrv_ms"] is None


async def test_undeclared_history_does_not_feed_a_declared_reading(async_db) -> None:
    """NULL is its own bucket, not a wildcard. Unknown is never 'assumed rMSSD'."""
    user = await _user(async_db, "hrvm-null@test.com")
    uid = user.id
    for i in range(1, 11):
        await _sample(async_db, uid, _TODAY - timedelta(days=i), "manual", hrv_ms=44.0)

    declared = await _baselines(
        async_db,
        uid,
        before=_TODAY,
        source_by_signal={"hrv_ms": "manual"},
        metric_by_signal={"hrv_ms": "rmssd"},
    )
    undeclared = await _baselines(
        async_db, uid, before=_TODAY, source_by_signal={"hrv_ms": "manual"}
    )

    assert declared["hrv_ms"] is None, "undeclared history must not back a declared reading"
    assert undeclared["hrv_ms"] == 44.0, "undeclared history still backs an undeclared reading"


async def test_other_signals_are_untouched_by_the_metric_filter(async_db) -> None:
    """Only hrv_ms carries a metric; every other signal must behave exactly as before."""
    user = await _user(async_db, "hrvm-others@test.com")
    uid = user.id
    for i in range(1, 11):
        await _sample(
            async_db, uid, _TODAY - timedelta(days=i), "oura",
            resting_hr=55.0, sleep_hours=7.0, hrv_ms=60.0, hrv_metric="rmssd",
        )

    out = await _baselines(
        async_db,
        uid,
        before=_TODAY,
        source_by_signal={"hrv_ms": "oura", "resting_hr": "oura", "sleep_hours": "oura"},
        metric_by_signal={"hrv_ms": "sdnn"},  # excludes HRV only
    )

    assert out["hrv_ms"] is None
    assert out["resting_hr"] == 55.0
    assert out["sleep_hours"] == 7.0


async def test_resolve_day_reports_the_winning_rows_metric(async_db) -> None:
    """The baseline is only correct if today's metric is reported alongside today's source."""
    user = await _user(async_db, "hrvm-resolve@test.com")
    uid = user.id
    await _sample(async_db, uid, _TODAY, "oura", hrv_ms=52.0, hrv_metric="rmssd")

    values, sources, metrics = await _resolve_day(async_db, uid, _TODAY)

    assert values["hrv_ms"] == 52.0
    assert sources["hrv_ms"] == "oura"
    assert metrics["hrv_ms"] == "rmssd"


async def test_resolve_day_reports_an_undeclared_metric_as_a_present_none(async_db) -> None:
    """Presence and value carry different meanings, and both are load-bearing.

    A present key holding ``None`` says "today's reading is undeclared, so compare it only
    against other undeclared history". An absent key would instead mean "no metric filter at
    all", which would pool an undeclared reading against declared history — the very bug this
    column exists to prevent. The two must not collapse.
    """
    user = await _user(async_db, "hrvm-resolve-null@test.com")
    uid = user.id
    await _sample(async_db, uid, _TODAY, "manual", hrv_ms=52.0)

    _, _, metrics = await _resolve_day(async_db, uid, _TODAY)

    assert "hrv_ms" in metrics, "an undeclared reading must still constrain its baseline"
    assert metrics["hrv_ms"] is None, "and it must not be guessed into a concrete metric"


async def test_the_vocabulary_is_enforced_at_the_write(async_db) -> None:
    """A provider mapping that starts emitting an unrecognized label fails loudly.

    Silently accepting it would create a third baseline bucket and quietly halve every
    affected athlete's usable history.
    """
    user = await _user(async_db, "hrvm-vocab@test.com")
    with pytest.raises(IntegrityError):
        await _sample(
            async_db, user.id, _TODAY, "somewatch", hrv_ms=60.0, hrv_metric="pnn50"
        )
    await async_db.rollback()
