"""
app/api/v1/weak_points.py

Standalone weak-point management routes.
Allows the frontend to list and update weak-point rows without going
through benchmark observations.

Weak points are never hard-deleted: resolving one is a PATCH that sets
`resolved_at` (see docs/Data_Model.md, "Weak-point resolution"). Hard
deletion would also destroy the `source_session_id` benchmark provenance.

Data access and the transaction boundary live in
`app/services/weak_point_service.py`; this module owns HTTP concerns only.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.db import get_db
from app.models.user import User
from app.schemas.weak_point import WeakPointOut, WeakPointPatch
from app.services import weak_point_service

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
    rows = await weak_point_service.list_weak_points(
        db, current_user.id, active_only=active_only
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
    wp = await weak_point_service.patch_weak_point(
        db, current_user.id, weak_point_id, patch
    )
    if wp is None:
        raise HTTPException(status_code=404, detail="Weak point not found")
    return WeakPointOut.model_validate(wp)
