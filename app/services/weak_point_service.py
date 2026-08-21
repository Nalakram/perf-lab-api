"""Weak-point reads and partial updates.

Owns the transaction boundary for weak-point mutations (commit + refresh) and the
partial-update policy. Persistence mechanics stay in :class:`WeakPointRepository`,
which is read-only by design (see its module docstring) — the repository is
constructed per call, the house pattern for service-owned repository access.

Missing and not-owned are deliberately the same outcome: both return ``None``, and
the router turns that into a 404. Collapsing them prevents cross-user
resource-existence disclosure, and the ownership predicate lives inside the query
(``get_for_user``) rather than in a separate check, so there is no check-then-fetch
gap. Returning ``None`` rather than raising keeps fastapi out of this module, so a
non-HTTP caller can choose its own error policy.

``WeakPointPatch`` is treated as an immutable command value — read, never mutated.
"""
from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.weak_point import WeakPoint
from app.repositories.weak_point_repository import WeakPointRepository
from app.schemas.weak_point import WeakPointPatch


async def list_weak_points(
    db: AsyncSession, user_id: int, *, active_only: bool = True
) -> Sequence[WeakPoint]:
    """Weak-point rows owned by ``user_id``.

    When ``active_only`` is true (the default), only unresolved rows are returned.
    """
    return await WeakPointRepository(db).list_for_user(user_id, active_only=active_only)


async def patch_weak_point(
    db: AsyncSession, user_id: int, weak_point_id: int, patch: WeakPointPatch
) -> WeakPoint | None:
    """Apply ``patch`` to the weak point ``weak_point_id`` owned by ``user_id``.

    Only fields explicitly present in the request body are applied — presence is
    read from ``model_fields_set``, so an explicit JSON null is distinguishable from
    an omitted field and the two are handled differently per column.

    Returns ``None`` when the row does not exist or is not owned by ``user_id``
    (router → 404, house idiom).
    """
    wp = await WeakPointRepository(db).get_for_user(weak_point_id, user_id)
    if wp is None:
        return None

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
    return wp
