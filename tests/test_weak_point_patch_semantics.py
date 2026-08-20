"""Characterization tests for PATCH /v1/weak-points/{id} partial-update semantics.

These pin the three behaviors the route's partial-update contract depends on but
which `test_weak_point_routes.py` does not exercise. That file does assert one
field value (a `note` round-trip), but nothing there discriminates absent from
explicit-null, pins the tz handling, or proves persistence:

  1. A field absent from the request body is left untouched.
  2. An explicit JSON ``null`` is discriminated from an absent field, and the two
     nullable-in-transport fields resolve it differently: ``note`` accepts the null
     (the column is nullable), while ``confidence`` treats it as a no-op (the column
     is NOT NULL, so an explicit null must not reach it).
  3. A tz-aware ``resolved_at`` has its offset *dropped*, not converted.

(3) characterizes current behavior; it is deliberately **not** an endorsement of it.
``replace(tzinfo=None)`` discards the offset without converting the instant, so
``10:00-04:00`` persists as naive ``10:00``, not as naive-UTC ``14:00``. Correcting
that changes persisted instants and needs a migration decision, so it is tracked as a
separate correctness candidate. This test exists so that a refactor cannot change the
behavior silently, and so a future fix has to change this test on purpose.

The fourth test proves the mutation is actually *committed*, not merely mutated in
memory. The ``async_db`` fixture builds its session with ``expire_on_commit=False``
(conftest.py), so a read through that same session is served from the identity map and
cannot distinguish "committed" from "assigned and never persisted". Only a session with
its own identity map can tell the difference.
"""
from datetime import datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from app.core.auth import get_current_user
from app.core.db import get_db
from app.main import app
from app.models.user import User
from app.models.weak_point import WeakPoint, WeakPointSource
from tests.conftest import TEST_DATABASE_URL

pytestmark = pytest.mark.asyncio

# Fixed, naive — matching the column convention — so assertions are deterministic.
_DETECTED_AT = datetime(2026, 8, 1, 12, 0, 0)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _mk_user(db, email: str) -> User:
    u = User(email=email, hashed_password="hashed", is_active=True)
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


async def _mk_weak_point(
    db,
    user_id: int,
    *,
    tag: str = "grip",
    confidence: float = 0.5,
    note: str | None = None,
    resolved_at: datetime | None = None,
) -> WeakPoint:
    wp = WeakPoint(
        user_id=user_id,
        tag=tag,
        source=WeakPointSource.SELF_REPORT,
        confidence=confidence,
        note=note,
        detected_at=_DETECTED_AT,
        resolved_at=resolved_at,
    )
    db.add(wp)
    await db.commit()
    await db.refresh(wp)
    return wp


def _override(db, user) -> None:
    async def _override_db():
        yield db

    async def _override_user():
        return user

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = _override_user


# ---------------------------------------------------------------------------
# REQ-1 — an absent field is left unchanged
# ---------------------------------------------------------------------------

async def test_absent_fields_are_left_unchanged(async_db):
    """An empty PATCH body changes nothing: every governed column keeps its value."""
    user = await _mk_user(async_db, email="wp-sem-absent@test.com")
    wp = await _mk_weak_point(
        async_db,
        user.id,
        confidence=0.75,
        note="original note",
        resolved_at=datetime(2026, 8, 5, 9, 30, 0),
    )

    _override(async_db, user)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.patch(f"/v1/weak-points/{wp.id}", json={})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["confidence"] == 0.75
        assert data["note"] == "original note"
        assert data["resolved_at"] == "2026-08-05T09:30:00"
        assert data["is_active"] is False
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# REQ-2 — an explicit null is discriminated from an absent field
# ---------------------------------------------------------------------------

async def test_explicit_null_is_discriminated_from_an_absent_field(async_db):
    """``note: null`` clears the column; ``confidence: null`` is a no-op.

    Both fields are ``| None`` in the patch schema, so absent and explicit-null are
    indistinguishable by value alone — only ``model_fields_set`` separates them. The
    two columns then diverge: ``note`` is nullable and takes the null, while
    ``confidence`` is NOT NULL and the explicit null must be ignored rather than
    written (or rejected).
    """
    user = await _mk_user(async_db, email="wp-sem-null@test.com")
    note_row = await _mk_weak_point(
        async_db, user.id, tag="grip", confidence=0.6, note="will be cleared"
    )
    conf_row = await _mk_weak_point(
        async_db, user.id, tag="core", confidence=0.75, note="untouched"
    )

    _override(async_db, user)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            note_resp = await client.patch(
                f"/v1/weak-points/{note_row.id}", json={"note": None}
            )
            conf_resp = await client.patch(
                f"/v1/weak-points/{conf_row.id}", json={"confidence": None}
            )

        assert note_resp.status_code == 200, note_resp.text
        assert note_resp.json()["note"] is None, "explicit null must clear a nullable column"

        assert conf_resp.status_code == 200, conf_resp.text
        assert conf_resp.json()["confidence"] == 0.75, (
            "explicit null on a NOT NULL column must be a no-op, not a write"
        )
        assert conf_resp.json()["note"] == "untouched"
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# REQ-3 — a tz-aware resolved_at has its offset dropped, not converted
# ---------------------------------------------------------------------------

async def test_tz_aware_resolved_at_drops_the_offset_without_converting(async_db):
    """A non-UTC offset is discarded, not normalized to UTC — and null re-opens.

    CHARACTERIZATION, NOT ENDORSEMENT: ``10:00-04:00`` is the instant ``14:00Z``, but
    the route stores naive ``10:00``. Fixing that is a separate, migration-bearing
    change; this test's job is to make the current behavior impossible to alter by
    accident.
    """
    user = await _mk_user(async_db, email="wp-sem-tz@test.com")
    wp = await _mk_weak_point(async_db, user.id, confidence=0.5)

    _override(async_db, user)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resolved = await client.patch(
                f"/v1/weak-points/{wp.id}",
                json={"resolved_at": "2026-08-20T10:00:00-04:00"},
            )
            assert resolved.status_code == 200, resolved.text
            assert resolved.json()["resolved_at"] == "2026-08-20T10:00:00", (
                "offset is dropped, not converted; UTC conversion would give 14:00:00"
            )
            assert resolved.json()["is_active"] is False

            reopened = await client.patch(
                f"/v1/weak-points/{wp.id}", json={"resolved_at": None}
            )
            assert reopened.status_code == 200, reopened.text
            assert reopened.json()["resolved_at"] is None
            assert reopened.json()["is_active"] is True
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# REQ-4 — the mutation is committed, proven through an independent session
# ---------------------------------------------------------------------------

async def test_patch_persists_and_is_visible_to_an_independent_session(async_db):
    """The patched row is readable through a session with its own identity map.

    A same-session read cannot prove persistence here: ``async_db`` is built with
    ``expire_on_commit=False``, so the ORM serves the in-memory object whether or not
    the commit ever reached Postgres. A separate session is what makes the assertion
    able to fail if the commit were removed.
    """
    user = await _mk_user(async_db, email="wp-sem-persist@test.com")
    wp = await _mk_weak_point(async_db, user.id, confidence=0.5, note=None)

    _override(async_db, user)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.patch(
                f"/v1/weak-points/{wp.id}",
                json={
                    "confidence": 0.95,
                    "note": "persisted note",
                    "resolved_at": "2026-08-19T08:15:00",
                },
            )
        assert resp.status_code == 200, resp.text
    finally:
        app.dependency_overrides.clear()

    engine = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)
    try:
        factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as fresh_session:
            result = await fresh_session.execute(
                select(WeakPoint).where(WeakPoint.id == wp.id)
            )
            persisted = result.scalars().one()
            assert persisted.confidence == 0.95
            assert persisted.note == "persisted note"
            assert persisted.resolved_at == datetime(2026, 8, 19, 8, 15, 0)
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# Ownership — missing and not-owned must stay indistinguishable
# ---------------------------------------------------------------------------

async def test_patching_another_users_weak_point_is_indistinguishable_from_missing(
    async_db,
):
    """A row owned by someone else 404s with the same body as a nonexistent id.

    The ownership predicate lives inside the fetch (``get_for_user`` filters on
    ``user_id``), so missing and not-owned collapse to one outcome deliberately:
    distinguishing them — e.g. by fetching first and raising 403 on an owner
    mismatch — would disclose that another user's row exists. That is the security
    property the service module docstring claims, so it is asserted here rather
    than trusted, and it guards the module the logic just moved into.
    """
    owner = await _mk_user(async_db, email="wp-sem-owner@test.com")
    intruder = await _mk_user(async_db, email="wp-sem-intruder@test.com")
    victim_row = await _mk_weak_point(async_db, owner.id, note="not yours")

    _override(async_db, intruder)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            foreign = await client.patch(
                f"/v1/weak-points/{victim_row.id}", json={"note": "pwned"}
            )
            missing = await client.patch("/v1/weak-points/99999", json={"note": "pwned"})

        assert foreign.status_code == 404, foreign.text
        assert missing.status_code == 404, missing.text
        # Identical bodies: the response must not leak that the row exists.
        assert foreign.json() == missing.json()
        assert foreign.json()["detail"] == "Weak point not found"
    finally:
        app.dependency_overrides.clear()

    # And the row must be untouched.
    await async_db.refresh(victim_row)
    assert victim_row.note == "not yours"


# ---------------------------------------------------------------------------
# list active_only — the service default is not reachable from HTTP
# ---------------------------------------------------------------------------

async def test_list_active_only_false_includes_resolved_rows(async_db):
    """``active_only=false`` returns resolved rows; the default excludes them.

    The router always passes ``active_only`` explicitly, so the service's own
    default is unreachable over HTTP and nothing else pins it. Both directions are
    asserted here so that flipping either default is a test failure rather than a
    silent change in what a caller receives.
    """
    user = await _mk_user(async_db, email="wp-sem-activeonly@test.com")
    await _mk_weak_point(async_db, user.id, tag="grip")
    await _mk_weak_point(
        async_db, user.id, tag="core", resolved_at=datetime(2026, 8, 10, 7, 0, 0)
    )

    _override(async_db, user)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            default = await client.get("/v1/weak-points/")
            including = await client.get("/v1/weak-points/?active_only=false")

        assert default.status_code == 200, default.text
        assert [r["tag"] for r in default.json()] == ["grip"]

        assert including.status_code == 200, including.text
        assert sorted(r["tag"] for r in including.json()) == ["core", "grip"]
    finally:
        app.dependency_overrides.clear()
