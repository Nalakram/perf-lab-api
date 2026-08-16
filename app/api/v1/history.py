"""
app/api/v1/history.py

Read-only history over data the app already persists: the athlete's state
vectors over time (athlete_states) and their logged workouts (workout_logs).
These back the previously-mocked trend/time-travel views (Twin time-travel,
History readiness trend & weekly load, recent sessions) with real data.

Both reads go through the repository seam + a state_service loader (AUD-C15) —
the routes no longer own AthleteState query or unified_from_athlete_row
conversion knowledge (see CONTEXT.md).

No route here constructs a repository: each handler calls exactly one loader
(load_recent_state_snapshots / load_recent_workouts) and returns what it gets,
so no ORM row and no persistence handle reaches a handler body. The
``/v1/workouts`` handler once held ``AthleteContextRepository(db)`` inline,
which is what tests/test_athlete_state_seam.py now guards against.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.db import get_db
from app.models.user import User
from app.schemas.history import WorkoutLogSummary
from app.schemas.state import StateHistorySnapshotRead
from app.services import state_service

router = APIRouter(prefix="/v1", tags=["history"])


@router.get("/state-history", response_model=list[StateHistorySnapshotRead])
async def state_history(
    limit: int = Query(60, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[StateHistorySnapshotRead]:
    """The athlete's recent recorded state snapshots, oldest→newest (scrub order).

    Each snapshot carries a per-axis confidence-presentation band derived from that
    row's own variance (ADR-0059), so the Twin can render certainty without
    re-declaring the policy thresholds client-side.
    """
    return await state_service.load_recent_state_snapshots(db, current_user.id, limit)


@router.get("/workouts", response_model=list[WorkoutLogSummary])
async def list_workouts(
    limit: int = Query(50, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[WorkoutLogSummary]:
    """The athlete's logged workouts, most recent first."""
    return await state_service.load_recent_workouts(db, current_user.id, limit)
