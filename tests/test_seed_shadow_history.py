"""The service-layer replay seeder actually populates the shadow tables.

``app/scripts/*`` is excluded from coverage and the pyright gate, so a changed service
signature breaks a seeder silently until a human runs it. That risk is higher for this one
than for the catalog seeders: it is the only script that drives ``app.services`` rather than
constructing ORM rows, so it is coupled to the signatures of ``initialize_athlete_state``,
``process_new_workout``, ``upsert_wellness_sample`` and the three shadow writers at once.

The assertion that matters is not "rows exist" but WHICH rows. A replay that skipped S0
would still write wellness samples — and nothing else — because every shadow writer returns
silently without a current state. So this pins the shadow tables specifically, since those
are the ones the whole script exists to fill.

Runs with ``with_forecasts=False``: the prescription leg needs the exercise catalog, which
would make this a fixture-dependent test rather than a hermetic one. The forecast leg is
covered by running the script for real, not here.

Requires a live PostgreSQL instance (async_db fixture).
"""
from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.athlete_state import AthleteState
from app.models.ekf_shadow import EkfShadowLog
from app.models.recovery_shadow import RecoveryShadowLog
from app.models.user import User
from app.models.wellness import WellnessSample
from app.scripts import seed_shadow_history

pytestmark = pytest.mark.asyncio

_DAYS = 8


async def _count(db: AsyncSession, model: type) -> int:
    return (await db.execute(select(func.count()).select_from(model))).scalar_one()


async def _create_user(db: AsyncSession, email: str = "replay@example.com") -> User:
    user = User(email=email, hashed_password="hashed", is_active=True)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def test_replay_populates_shadow_tables_and_is_idempotent(
    async_db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The script opens its own session; point it at this worker's test database.
    test_factory = async_sessionmaker(async_db.bind, expire_on_commit=False)
    monkeypatch.setattr(seed_shadow_history, "AsyncSessionLocal", test_factory)

    await _create_user(async_db)

    await seed_shadow_history.seed(n_users=1, days=_DAYS, with_forecasts=False)
    await async_db.rollback()  # end this test's snapshot so it sees the script's commits

    wellness = await _count(async_db, WellnessSample)
    states = await _count(async_db, AthleteState)
    recovery = await _count(async_db, RecoveryShadowLog)
    ekf_updates = (
        await async_db.execute(
            select(func.count())
            .select_from(EkfShadowLog)
            .where(EkfShadowLog.event_type == "update")
        )
    ).scalar_one()

    assert wellness == _DAYS, "one wellness sample per simulated day"
    # S0 plus one row per logged workout — proves the baseline was established rather than
    # left to the implicit path, which is what the shadow writers depend on.
    assert states > 1, "replay must create S0 and then advance the state timeline"
    assert recovery == _DAYS, "every wellness day must produce a recovery shadow row"
    # The distinguishing assertion: `update` rows come only from assimilated wellness, and
    # only when a current state exists. Zero here means the replay wrote samples nobody read.
    assert ekf_updates == _DAYS, f"expected {_DAYS} assimilated EKF updates, got {ekf_updates}"

    # Idempotent: the athlete now has a state timeline, so a second pass skips them whole
    # rather than duplicating the history (process_new_workout appends, it does not upsert).
    await seed_shadow_history.seed(n_users=1, days=_DAYS, with_forecasts=False)
    await async_db.rollback()

    assert await _count(async_db, WellnessSample) == wellness
    assert await _count(async_db, AthleteState) == states
    assert await _count(async_db, RecoveryShadowLog) == recovery
