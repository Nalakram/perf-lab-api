"""One session, one penalty — the adherence aggregate's authority rules (ADR-0070).

`PlannedSession.status` owns whether a session happened; `SessionFeedback` adds only
whether it was changed. These tests pin the seam where those two could disagree, and
the prescriber-side consequence of the combined signal.

The DB-backed tests assert through `block_adherence_signals` because that aggregate is
the prescriber's only adherence input — anything it double-counts, the athlete pays for
twice.
"""

from datetime import UTC, date, datetime, timedelta

import pytest

from app.logic.prescriber import recommend_next_session
from app.models.mesocycle import (
    BlockGoal,
    BlockStatus,
    MesocycleBlock,
    PlannedSession,
    SessionStatus,
)
from app.models.telemetry import SessionFeedback
from app.models.user import User
from app.schemas.state import UnifiedStateVector
from app.services.planning_service import block_adherence_signals

pytestmark = pytest.mark.asyncio


async def _mk_user(db, email: str) -> User:
    u = User(email=email, hashed_password="hashed", is_active=True)
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


async def _mk_block(db, user_id: int, *, start: date | None = None) -> MesocycleBlock:
    block = MesocycleBlock(
        user_id=user_id,
        goal=BlockGoal.STRENGTH,
        status=BlockStatus.ACTIVE,
        duration_weeks=4,
        start_date=start or date.today(),
        weekly_template=[],
    )
    db.add(block)
    await db.commit()
    await db.refresh(block)
    return block


async def _mk_session(
    db, user_id: int, block_id: int, status: SessionStatus, *, day: int = 1
) -> PlannedSession:
    ps = PlannedSession(
        block_id=block_id,
        user_id=user_id,
        scheduled_date=date.today(),
        week_number=1,
        day_of_week=day,
        category="Heavy Lower",
        modality="strength",
        status=status,
    )
    db.add(ps)
    await db.commit()
    await db.refresh(ps)
    return ps


async def _mk_feedback(db, planned_session_id: int, **flags) -> SessionFeedback:
    fb = SessionFeedback(
        planned_session_id=planned_session_id,
        status=flags.pop("status", "completed"),
        **flags,
    )
    db.add(fb)
    await db.commit()
    return fb


# --- The double-count seam ---------------------------------------------------


async def test_a_skipped_session_the_athlete_also_called_modified_counts_once(async_db):
    """The failure this whole contract exists to prevent.

    A skipped session with a feedback row flagging modification is ONE piece of
    adherence evidence. Counting it as both a skip and a modification would penalise
    the athlete twice for a single missed session.
    """
    user = await _mk_user(async_db, "adh-double@test.com")
    block = await _mk_block(async_db, user.id)
    ps = await _mk_session(async_db, user.id, block.id, SessionStatus.SKIPPED)
    await _mk_feedback(async_db, ps.id, status="skipped", modified_volume=True)

    signals = await block_adherence_signals(async_db, user.id, block.id)

    assert signals["recent_skips"] == 1
    assert signals["recent_modifications"] == 0


async def test_status_wins_over_the_report_because_occurrence_is_its_to_own(async_db):
    """A completed session reported as modified is a modification, not a skip."""
    user = await _mk_user(async_db, "adh-completed@test.com")
    block = await _mk_block(async_db, user.id)
    ps = await _mk_session(async_db, user.id, block.id, SessionStatus.COMPLETED)
    await _mk_feedback(async_db, ps.id, status="modified", modified_intensity=True)

    signals = await block_adherence_signals(async_db, user.id, block.id)

    assert signals["recent_skips"] == 0
    assert signals["recent_modifications"] == 1


async def test_an_unmodified_completed_session_is_not_friction(async_db):
    user = await _mk_user(async_db, "adh-clean@test.com")
    block = await _mk_block(async_db, user.id)
    ps = await _mk_session(async_db, user.id, block.id, SessionStatus.COMPLETED)
    await _mk_feedback(async_db, ps.id, status="completed", followed_as_prescribed=True)

    signals = await block_adherence_signals(async_db, user.id, block.id)

    assert signals == {"recent_skips": 0, "recent_modifications": 0}


async def test_a_session_with_no_feedback_at_all_still_counts_its_skip(async_db):
    """Feedback is advisory; its absence must not erase what status already knows."""
    user = await _mk_user(async_db, "adh-nofb@test.com")
    block = await _mk_block(async_db, user.id)
    await _mk_session(async_db, user.id, block.id, SessionStatus.SKIPPED)

    signals = await block_adherence_signals(async_db, user.id, block.id)

    assert signals["recent_skips"] == 1


# --- Scope: recency is the block, derived from the session -------------------


async def test_another_blocks_sessions_do_not_leak_in(async_db):
    """Recency is block membership. An older block's friction is not today's."""
    user = await _mk_user(async_db, "adh-scope@test.com")
    old = await _mk_block(async_db, user.id, start=date.today() - timedelta(days=90))
    current = await _mk_block(async_db, user.id)
    await _mk_session(async_db, user.id, old.id, SessionStatus.SKIPPED)
    await _mk_session(async_db, user.id, old.id, SessionStatus.SKIPPED, day=2)

    signals = await block_adherence_signals(async_db, user.id, current.id)

    assert signals == {"recent_skips": 0, "recent_modifications": 0}


async def test_another_athletes_block_does_not_leak_in(async_db):
    mine = await _mk_user(async_db, "adh-mine@test.com")
    theirs = await _mk_user(async_db, "adh-theirs@test.com")
    their_block = await _mk_block(async_db, theirs.id)
    await _mk_session(async_db, theirs.id, their_block.id, SessionStatus.SKIPPED)

    signals = await block_adherence_signals(async_db, mine.id, their_block.id)

    assert signals == {"recent_skips": 0, "recent_modifications": 0}


# --- Prescriber consequence --------------------------------------------------


def _healthy_state() -> UnifiedStateVector:
    return UnifiedStateVector(
        timestamp=datetime.now(UTC),
        c_met_aerobic=50.0,
        c_nm_force=50.0,
        c_struct=50.0,
        b_met_anaerobic=50.0,
        f_met_systemic=20.0,
        f_nm_peripheral=15.0,
        f_nm_central=20.0,
        f_struct_damage=10.0,
        s_struct_signal=20.0,
        habit_strength=0.6,
        skill_state={"squat": 0.7},
    )


@pytest.mark.parametrize(
    "block_context",
    [
        {"recent_skips": 3},
        {"recent_skips": 3, "recent_modifications": 0},
    ],
)
def test_no_reported_modifications_prescribes_exactly_what_it_did_before(block_context):
    """The new signal is additive: at zero modifications the bias is unchanged.

    Pinned so a future weight change cannot silently move every existing athlete's
    prescription — an absent report must never behave like a reported one.
    """
    rx = recommend_next_session(_healthy_state(), goal="Running", block_context=block_context)
    assert rx.why is not None
    assert "adherence:recent_skips=3" in rx.why.constraints_applied
    assert not any("recent_modifications" in c for c in rx.why.constraints_applied)


def test_reported_modifications_alone_can_raise_the_bias():
    """Deviation is evidence even when every session was completed."""
    rx = recommend_next_session(
        _healthy_state(), goal="Running", block_context={"recent_modifications": 4}
    )
    assert rx.why is not None
    assert "adherence:recent_modifications=4" in rx.why.constraints_applied
    assert not any("recent_skips" in c for c in rx.why.constraints_applied)


def test_a_single_modification_is_not_enough_to_bias():
    """One changed session is noise, not friction — the threshold still applies."""
    rx = recommend_next_session(
        _healthy_state(), goal="Running", block_context={"recent_modifications": 1}
    )
    assert rx.why is not None
    assert not any("adherence:" in c for c in rx.why.constraints_applied)


def test_the_explanation_names_both_components_when_both_contributed():
    """The athlete is owed the evidence, not a combined friction score."""
    rx = recommend_next_session(
        _healthy_state(),
        goal="Running",
        block_context={"recent_skips": 1, "recent_modifications": 2},
    )
    assert rx.why is not None
    assert "adherence:recent_skips=1" in rx.why.constraints_applied
    assert "adherence:recent_modifications=2" in rx.why.constraints_applied
