"""
app/api/v1/weak_points.py

Standalone weak-point management routes.
Allows the frontend to list and update weak-point rows without going
through benchmark observations.

Weak points are never hard-deleted: resolving one is a PATCH that sets
`resolved_at` (see docs/Data_Model.md, "Weak-point resolution"). Hard
deletion would also destroy the `source_session_id` benchmark provenance.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.db import get_db
from app.models.user import User
from app.repositories.weak_point_repository import WeakPointRepository
from app.schemas.weak_point import WeakPointOut, WeakPointPatch

router = APIRouter(prefix="/weak-points", tags=["Weak Points"])


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/", response_model=list[WeakPointOut])
async def list_weak_points(
    active_only: bool = True,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[WeakPointOut]:
    """Return all weak-point rows for the current user.

    By default only active (unresolved) rows are returned.
    Pass active_only=false to include resolved rows.
    """
    rows = await WeakPointRepository(db).list_for_user(
        current_user.id, active_only=active_only
    )
    return [WeakPointOut.model_validate(row) for row in rows]


@router.patch("/{weak_point_id}", response_model=WeakPointOut)
async def patch_weak_point(
    weak_point_id: int,
    patch: WeakPointPatch,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> WeakPointOut:
    """Update confidence, note, and/or resolved_at on a weak-point row.

    Only fields explicitly present in the request body are applied.
    Sending resolved_at=null re-opens a resolved weak point.
    """
    wp = await WeakPointRepository(db).get_for_user(weak_point_id, current_user.id)
    if wp is None:
        raise HTTPException(status_code=404, detail="Weak point not found")

    # Only apply fields that were explicitly set in the request body.
    # confidence maps to a NOT NULL column, so guard against an explicit null.
    if "confidence" in patch.model_fields_set and patch.confidence is not None:
        wp.confidence = patch.confidence
    if "note" in patch.model_fields_set:
        wp.note = patch.note
    if "resolved_at" in patch.model_fields_set:
        # Columns are naive-UTC; normalize an incoming tz-aware value so asyncpg
        # doesn't reject the naive-vs-aware bind on a TIMESTAMP column.
        rv = patch.resolved_at
        wp.resolved_at = rv.replace(tzinfo=None) if rv is not None and rv.tzinfo else rv

    await db.commit()
    await db.refresh(wp)
    return WeakPointOut.model_validate(wp)
