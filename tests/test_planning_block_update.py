"""Characterization tests for `PATCH /v1/planning/blocks/{id}` (`update_block`).

Written ahead of the PR2 router→service refactor (planning.py → planning_service.py)
because this route had zero existing test coverage — grepped the whole tests/ tree for
`/v1/planning/blocks/{id}` PATCH calls and found none. These pin the route-observable
behavior the refactor must not change:

- partial update via `if body.X is not None` semantics: an omitted field AND an
  explicit `null` both leave the stored value untouched (NOT `model_dump(exclude_unset=True)`,
  which the sibling `update_macrocycle` uses and which WOULD write an explicit null).
- 404 on a nonexistent or not-owned block id.
- a full-field update updates every field and the response reflects it.
"""

from datetime import date

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.auth import get_current_user
from app.core.db import get_db
from app.main import app
from app.models.user import AthleteProfile, User
from app.services.state_service import initialize_athlete_state

pytestmark = pytest.mark.asyncio


async def _mk_user(db, email: str) -> User:
    u = User(email=email, hashed_password="h", is_active=True)
    db.add(u)
    await db.commit()
    await db.refresh(u)
    profile = AthleteProfile(user_id=u.id, equipment=["dumbbells"])
    db.add(profile)
    await db.commit()
    await initialize_athlete_state(db, u.id)
    return u


def _override(db, user) -> None:
    async def _override_db():
        yield db

    async def _override_user():
        return user

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = _override_user


async def _create_block(client: AsyncClient) -> dict:
    resp = await client.post(
        "/v1/planning/blocks",
        json={
            "goal": "Strength",
            "start_date": date.today().isoformat(),
            "duration_weeks": 2,
            "sessions_per_week": 3,
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_omitted_field_leaves_it_unchanged(async_db):
    user = await _mk_user(async_db, "block-update-omit@test.com")
    _override(async_db, user)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            block = await _create_block(client)
            assert block["status"] == "active"
            assert block["rationale"] is None

            patch = await client.patch(
                f"/v1/planning/blocks/{block['id']}",
                json={"rationale": "R1"},
            )
            assert patch.status_code == 200, patch.text
            body = patch.json()
            assert body["rationale"] == "R1"
            # status, modality_mix, deload_volume_factor were not sent — unchanged.
            assert body["status"] == "active"
            assert body["deload_volume_factor"] == block["deload_volume_factor"]
    finally:
        app.dependency_overrides.clear()


async def test_explicit_null_also_leaves_it_unchanged(async_db):
    """`is not None` semantics: an explicit JSON null is indistinguishable from an
    omitted field. This is the divergence from `update_macrocycle`'s
    `model_dump(exclude_unset=True)` idiom, which WOULD apply an explicit null —
    the refactor must not silently adopt that idiom here."""
    user = await _mk_user(async_db, "block-update-null@test.com")
    _override(async_db, user)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            block = await _create_block(client)
            assert block["status"] == "active"

            patch = await client.patch(
                f"/v1/planning/blocks/{block['id']}",
                json={"status": None},
            )
            assert patch.status_code == 200, patch.text
            assert patch.json()["status"] == "active"
    finally:
        app.dependency_overrides.clear()


async def test_unowned_or_missing_block_returns_404(async_db):
    owner = await _mk_user(async_db, "block-update-owner@test.com")
    other = await _mk_user(async_db, "block-update-other@test.com")

    _override(async_db, owner)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            block = await _create_block(client)
    finally:
        app.dependency_overrides.clear()

    _override(async_db, other)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            patch = await client.patch(
                f"/v1/planning/blocks/{block['id']}",
                json={"rationale": "not yours"},
            )
            assert patch.status_code == 404

            missing = await client.patch(
                "/v1/planning/blocks/99999999",
                json={"rationale": "does not exist"},
            )
            assert missing.status_code == 404
    finally:
        app.dependency_overrides.clear()


async def test_full_field_update_persists_and_returns_every_field(async_db):
    user = await _mk_user(async_db, "block-update-full@test.com")
    _override(async_db, user)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            block = await _create_block(client)

            patch = await client.patch(
                f"/v1/planning/blocks/{block['id']}",
                json={
                    "status": "completed",
                    "rationale": "full update",
                    "modality_mix": {"strength": 1.0},
                    "deload_volume_factor": 0.5,
                },
            )
            assert patch.status_code == 200, patch.text
            body = patch.json()
            assert body["status"] == "completed"
            assert body["rationale"] == "full update"
            assert body["modality_mix"] == {"strength": 1.0}
            assert body["deload_volume_factor"] == 0.5

            # Persisted, not just echoed — a fresh GET reflects the same state.
            listed = await client.get("/v1/planning/blocks")
            assert listed.status_code == 200
            updated = next(b for b in listed.json() if b["id"] == block["id"])
            assert updated["status"] == "completed"
            assert updated["rationale"] == "full update"
    finally:
        app.dependency_overrides.clear()
