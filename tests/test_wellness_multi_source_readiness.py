"""Readiness must read every source that reported, and compare like against like.

Two defects lived in the same two DB helpers, and both are invisible until an athlete has
more than one wellness source — which the table's own (user, date, source) key is designed
to allow.

A. `_latest_wellness` returned ONE row ordered by `created_at`, so when an Oura sync and a
   manual check-in both landed the loser's signals were dropped. The athlete reported
   soreness and it was ignored, which also under-counted coverage and lowered their
   confidence for data they had actually supplied.

B. `_baselines` averaged every source together, so today's Oura HRV was compared against a
   28-day mean containing manual entries and any other device. Switching provider mid-window
   shifted the baseline, and the deviation was measured against a number no single
   instrument ever produced.
"""

from datetime import UTC, datetime, timedelta
from datetime import date as date_cls

from app.models.user import User
from app.models.wellness import WellnessSample
from app.services.readiness_service import _baselines, _resolve_day

_TODAY = date_cls(2026, 8, 23)


async def _user(db, email: str) -> User:
    u = User(email=email, hashed_password="x", is_active=True)
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


async def _sample(
    db, user_id: int, on: date_cls, source: str, *, ingested: datetime | None = None, **signals
) -> WellnessSample:
    row = WellnessSample(
        user_id=user_id,
        date=on,
        source=source,
        created_at=(ingested or datetime(2026, 8, 23, 6, 0, tzinfo=UTC)).replace(tzinfo=None),
        **signals,
    )
    db.add(row)
    await db.commit()
    return row


# ── A. every source that reported is read ─────────────────────────────────────


async def test_signals_from_a_second_source_are_no_longer_dropped(async_db) -> None:
    """The device supplies HRV, the athlete supplies soreness, on the same day.

    Before, only one row won and the other's signals vanished entirely.
    """
    user = await _user(async_db, "ws-merge@test.com")
    uid = user.id
    await _sample(async_db, uid, _TODAY, "oura", hrv_ms=70.0, sleep_hours=8.0)
    await _sample(
        async_db, uid, _TODAY, "manual",
        soreness=6.0, mood=4.0,
        ingested=datetime(2026, 8, 23, 20, 0, tzinfo=UTC),
    )

    values, sources = await _resolve_day(async_db, uid, _TODAY)

    assert values["hrv_ms"] == 70.0
    assert values["soreness"] == 6.0
    assert values["mood"] == 4.0
    assert sources["hrv_ms"] == "oura"
    assert sources["soreness"] == "manual"


async def test_the_device_wins_a_measured_signal_both_reported(async_db) -> None:
    """Both supplied HRV. The wearable measured it; the athlete estimated it."""
    user = await _user(async_db, "ws-objective@test.com")
    uid = user.id
    # Manual lands LAST, so insertion order would have picked it under the old rule.
    await _sample(async_db, uid, _TODAY, "oura", hrv_ms=70.0)
    await _sample(
        async_db, uid, _TODAY, "manual", hrv_ms=45.0,
        ingested=datetime(2026, 8, 23, 22, 0, tzinfo=UTC),
    )

    values, sources = await _resolve_day(async_db, uid, _TODAY)

    assert values["hrv_ms"] == 70.0
    assert sources["hrv_ms"] == "oura"


async def test_the_athlete_wins_a_felt_signal_both_reported(async_db) -> None:
    """A provider-inferred stress score does not override the person feeling it."""
    user = await _user(async_db, "ws-subjective@test.com")
    uid = user.id
    await _sample(async_db, uid, _TODAY, "manual", stress=2.0)
    await _sample(
        async_db, uid, _TODAY, "oura", stress=9.0,
        ingested=datetime(2026, 8, 23, 23, 0, tzinfo=UTC),
    )

    values, sources = await _resolve_day(async_db, uid, _TODAY)

    assert values["stress"] == 2.0
    assert sources["stress"] == "manual"


async def test_a_signal_nobody_reported_stays_missing(async_db) -> None:
    user = await _user(async_db, "ws-missing@test.com")
    uid = user.id
    await _sample(async_db, uid, _TODAY, "oura", hrv_ms=70.0)

    values, sources = await _resolve_day(async_db, uid, _TODAY)

    assert values["soreness"] is None
    assert "soreness" not in sources


# ── B. baselines compare like against like ────────────────────────────────────


async def test_a_baseline_uses_only_the_source_that_produced_todays_value(async_db) -> None:
    """The provider-switch bug, in the shape it actually occurs.

    Fourteen days of manual HRV around 50, then a device reporting around 70. Pooling gives
    a baseline near 60 and reports the athlete as well above their norm on day one of a new
    device — an artefact of the instrument change, not a recovery.
    """
    user = await _user(async_db, "ws-baseline@test.com")
    uid = user.id
    for i in range(1, 15):
        await _sample(async_db, uid, _TODAY - timedelta(days=i), "manual", hrv_ms=50.0)
    for i in range(1, 4):
        await _sample(async_db, uid, _TODAY - timedelta(days=i), "oura", hrv_ms=70.0)

    pooled = await _baselines(async_db, uid, before=_TODAY)
    per_source = await _baselines(
        async_db, uid, before=_TODAY, source_by_signal={"hrv_ms": "oura"}
    )

    assert pooled["hrv_ms"] is not None and 50.0 < pooled["hrv_ms"] < 70.0
    assert per_source["hrv_ms"] == 70.0


async def test_a_brand_new_source_has_no_baseline_rather_than_borrowing_one(async_db) -> None:
    """The honest cost of switching providers: the personal baseline restarts.

    The new device's offset for this athlete is genuinely unknown, so the caller falls back
    to the population anchor exactly as for a new athlete. Silently reusing the old
    provider's mean would be the imputation defect in a new place.
    """
    user = await _user(async_db, "ws-newsource@test.com")
    uid = user.id
    for i in range(1, 15):
        await _sample(async_db, uid, _TODAY - timedelta(days=i), "manual", hrv_ms=50.0)

    per_source = await _baselines(
        async_db, uid, before=_TODAY, source_by_signal={"hrv_ms": "garmin"}
    )

    assert per_source["hrv_ms"] is None


async def test_omitting_the_source_map_keeps_the_pooled_behaviour(async_db) -> None:
    """Back-compatible default, so any other caller is unaffected."""
    user = await _user(async_db, "ws-pooled@test.com")
    uid = user.id
    await _sample(async_db, uid, _TODAY - timedelta(days=1), "manual", hrv_ms=40.0)
    await _sample(async_db, uid, _TODAY - timedelta(days=1), "oura", hrv_ms=60.0)

    pooled = await _baselines(async_db, uid, before=_TODAY)

    assert pooled["hrv_ms"] == 50.0


async def test_the_baseline_window_still_excludes_today(async_db) -> None:
    """Guards against the fix accidentally letting today leak into its own baseline."""
    user = await _user(async_db, "ws-window@test.com")
    uid = user.id
    await _sample(async_db, uid, _TODAY, "oura", hrv_ms=99.0)
    await _sample(async_db, uid, _TODAY - timedelta(days=1), "oura", hrv_ms=70.0)

    per_source = await _baselines(
        async_db, uid, before=_TODAY, source_by_signal={"hrv_ms": "oura"}
    )

    assert per_source["hrv_ms"] == 70.0
