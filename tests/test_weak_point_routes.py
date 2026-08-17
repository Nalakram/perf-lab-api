"""
Route contract tests for /v1/weak-points endpoints.

Tests run against a live test database (via async_db fixture from conftest.py).
DB-dependent tests are skipped automatically when no DB is available.

Five test functions covering both live routes × two status-code paths each,
plus one guarding the removed DELETE route:
  GET /v1/weak-points            → 200 (authenticated), 401 (unauthenticated)
  PATCH /v1/weak-points/{id}     → 200 (valid update), 404 (missing id)
  DELETE /v1/weak-points/{id}    → not routable (405); the row must survive
"""
from datetime import datetime

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.auth import get_current_user
from app.core.db import get_db
from app.main import app
from app.models.user import User
from app.models.weak_point import WeakPoint, WeakPointSource

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _mk_user(db, email: str = "wp-routes@test.com") -> User:
    u = User(email=email, hashed_password="hashed", is_active=True)
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


async def _mk_weak_point(db, user_id: int) -> WeakPoint:
    wp = WeakPoint(
        user_id=user_id,
        tag="grip",
        source=WeakPointSource.SELF_REPORT,
        confidence=0.5,
        note=None,
        detected_at=datetime.utcnow(),  # naive UTC — matches the column convention
    )
    db.add(wp)
    await db.commit()
    await db.refresh(wp)
    return wp


# ---------------------------------------------------------------------------
# GET /v1/weak-points
# ---------------------------------------------------------------------------

async def test_list_weak_points_returns_200_for_authenticated_user(async_db):
    """Authenticated GET /v1/weak-points returns 200 with an empty list for a fresh user."""
    user = await _mk_user(async_db, email="wp-list-200@test.com")

    async def _override_db():
        yield async_db

    async def _override_user():
        return user

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = _override_user

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/v1/weak-points/")
        assert resp.status_code == 200, resp.text
        assert resp.json() == []
    finally:
        app.dependency_overrides.clear()


async def test_list_weak_points_returns_401_for_unauthenticated_request(async_db):
    """GET /v1/weak-points without a token returns 401."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/v1/weak-points/")
    assert resp.status_code == 401, resp.text


# ---------------------------------------------------------------------------
# PATCH /v1/weak-points/{id}
# ---------------------------------------------------------------------------

async def test_patch_weak_point_returns_200_on_valid_update(async_db):
    """PATCH /v1/weak-points/{id} with a valid id returns 200 and the updated row."""
    user = await _mk_user(async_db, email="wp-patch-200@test.com")
    wp = await _mk_weak_point(async_db, user.id)

    async def _override_db():
        yield async_db

    async def _override_user():
        return user

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = _override_user

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.patch(
                f"/v1/weak-points/{wp.id}",
                json={"note": "grip failed on last set"},
            )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["id"] == wp.id
        assert data["note"] == "grip failed on last set"
    finally:
        app.dependency_overrides.clear()


async def test_patch_weak_point_returns_404_for_missing_id(async_db):
    """PATCH /v1/weak-points/99999 returns 404 when the row does not exist."""
    user = await _mk_user(async_db, email="wp-patch-404@test.com")

    async def _override_db():
        yield async_db

    async def _override_user():
        return user

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = _override_user

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.patch(
                "/v1/weak-points/99999",
                json={"note": "should not exist"},
            )
        assert resp.status_code == 404, resp.text
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# DELETE /v1/weak-points/{id} — removed route
# ---------------------------------------------------------------------------

async def test_delete_weak_point_is_not_routable(async_db):
    """DELETE /v1/weak-points/{id} is not a route: the row must survive the request.

    The weak-point lifecycle is PATCH-only (docs/Data_Model.md, "Weak-point
    resolution"): resolving sets `resolved_at`, nothing hard-deletes. The path
    still exists for PATCH, so Starlette matches the path and rejects the
    method with 405 rather than 404 — assert the exact status, and assert the
    row is still there so a future re-introduction of the handler cannot pass.
    """
    user = await _mk_user(async_db, email="wp-delete-gone@test.com")
    wp = await _mk_weak_point(async_db, user.id)

    async def _override_db():
        yield async_db

    async def _override_user():
        return user

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = _override_user

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.delete(f"/v1/weak-points/{wp.id}")
        assert resp.status_code == 405, resp.text

        still_there = await async_db.get(WeakPoint, wp.id)
        assert still_there is not None, "DELETE must not remove the row"
    finally:
        app.dependency_overrides.clear()
