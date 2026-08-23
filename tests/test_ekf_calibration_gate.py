"""ADR-0041's declared promotion gate must actually run on production rows.

ADR-0041 makes NIS chi-squared consistency over the production ``ekf_shadow_log`` the
evidence that decides promote vs stay_shadow. The math and the production feed both existed,
but ``build_ekf_calibration_records`` had **no caller anywhere** — grepping app/, tests/ and
scripts/ returned only its own ``def``. So every calibration figure in the repo came from an
offline synthetic simulation, and nothing would have noticed a live estimator drifting.

These tests pin the runner, and the last one pins the wiring itself so the feed cannot go
back to being dead code.
"""

import ast
from datetime import UTC, datetime
from pathlib import Path

from app.models.ekf_shadow import EkfShadowLog
from app.models.user import User
from app.services.ekf_calibration_gate_service import (
    ARM_COVERAGE,
    ARM_NIS,
    evaluate_ekf_calibration_gate,
    format_gate_report,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_FEED_FUNC = "build_ekf_calibration_records"


async def _user(db, email: str) -> User:
    u = User(email=email, hashed_password="x", is_active=True)
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


async def _seed_updates(db, user_id: int, *, n: int, nis: float, n_obs: int = 1) -> None:
    """Write ``n`` EKF update rows carrying a known NIS, so the gate has real rows to read."""
    for i in range(n):
        db.add(
            EkfShadowLog(
                user_id=user_id,
                belief_at=datetime.now(UTC).replace(tzinfo=None),
                model_version="test-v1",
                event_type="update",
                mean_json={},
                variance_json={},
                covariance_json=[],
                benchmark_code=f"bm_{i}",
                nis=nis,
                n_obs=n_obs,
                decision_impact="none_shadow_only",
            )
        )
    await db.commit()


# ── the gate on real rows ─────────────────────────────────────────────────────


async def test_empty_log_is_stay_shadow_not_a_pass(async_db) -> None:
    """No evidence must never read as a pass. It reads as blocked on insufficient updates."""
    result = await evaluate_ekf_calibration_gate(async_db)

    assert result["available"] is True
    assert result["verdict"] == "stay_shadow"
    assert result["n_updates"] == 0
    assert any("insufficient updates" in r for r in result["blocking_reasons"])
    assert result["promotion_authorized"] is False


async def test_well_calibrated_rows_produce_a_promote_verdict(async_db) -> None:
    """A filter whose NIS matches its dof clears the NIS arm.

    E[NIS] = n_obs for a calibrated filter, so 40 updates at nis=1.0 / n_obs=1 give a ratio
    of exactly 1.0 and total NIS 40 against dof 40 — comfortably inside the chi-squared band.
    """
    user = await _user(async_db, "ekfgate-ok@test.com")
    await _seed_updates(async_db, user.id, n=40, nis=1.0)

    result = await evaluate_ekf_calibration_gate(async_db)

    assert result["n_updates"] == 40
    assert result["dof"] == 40
    assert result["nis"]["ratio"] == 1.0
    assert result["blocking_reasons"] == []
    assert result["verdict"] == "promote"


async def test_overconfident_filter_is_blocked(async_db) -> None:
    """NIS far above dof means the filter's covariance is too small — the dangerous failure."""
    user = await _user(async_db, "ekfgate-over@test.com")
    await _seed_updates(async_db, user.id, n=40, nis=2.5)

    result = await evaluate_ekf_calibration_gate(async_db)

    assert result["verdict"] == "stay_shadow"
    assert result["nis"]["ratio"] == 2.5
    assert result["nis"]["overconfident"] is True
    assert any("NIS" in r for r in result["blocking_reasons"])


async def test_underconfident_filter_is_also_blocked(async_db) -> None:
    """The band is two-sided: a filter that is far too conservative is not calibrated either."""
    user = await _user(async_db, "ekfgate-under@test.com")
    await _seed_updates(async_db, user.id, n=40, nis=0.2)

    result = await evaluate_ekf_calibration_gate(async_db)

    assert result["verdict"] == "stay_shadow"
    assert result["nis"]["underconfident"] is True


async def test_scope_defaults_to_fleet_and_can_narrow_to_one_athlete(async_db) -> None:
    """A promotion decision is fleet-wide; per-athlete scoping is for inspection."""
    a = await _user(async_db, "ekfgate-a@test.com")
    b = await _user(async_db, "ekfgate-b@test.com")
    await _seed_updates(async_db, a.id, n=40, nis=1.0)
    await _seed_updates(async_db, b.id, n=10, nis=1.0)

    fleet = await evaluate_ekf_calibration_gate(async_db)
    just_b = await evaluate_ekf_calibration_gate(async_db, user_id=b.id)

    assert fleet["scope"] == "fleet"
    assert fleet["n_updates"] == 50
    assert just_b["scope"] == f"user:{b.id}"
    assert just_b["n_updates"] == 10
    # b alone is under MIN_UPDATES, so the narrow scope is correctly blocked.
    assert just_b["verdict"] == "stay_shadow"


# ── honesty guards ────────────────────────────────────────────────────────────


async def test_promote_never_claims_the_coverage_arm_ran(async_db) -> None:
    """ADR-0041 names two arms; production rows can only support one.

    ``ekf_shadow_log`` stores nis/n_obs but not the per-observation predictive std, so
    ``interval_coverage`` returns nan and ``calibration_report`` silently skips those levels.
    A ``promote`` from this gate is therefore a PARTIAL pass, and the payload has to say so —
    otherwise a reader takes one arm's verdict for both.
    """
    user = await _user(async_db, "ekfgate-arms@test.com")
    await _seed_updates(async_db, user.id, n=40, nis=1.0)

    result = await evaluate_ekf_calibration_gate(async_db)

    assert result["verdict"] == "promote"
    assert result["arms_evaluated"] == [ARM_NIS]
    assert ARM_COVERAGE in result["arms_not_evaluated"]
    assert result["arms_not_evaluated"][ARM_COVERAGE]


async def test_a_promote_verdict_still_authorizes_nothing(async_db) -> None:
    """There is no OFF/ON path for the EKF, so no verdict here can put it live.

    feature_flags.py records that five ENABLE_* booleans were deleted because a flag read by
    no production code is a fictional promotion gate. This gate must not become the next one.
    """
    user = await _user(async_db, "ekfgate-auth@test.com")
    await _seed_updates(async_db, user.id, n=40, nis=1.0)

    result = await evaluate_ekf_calibration_gate(async_db)

    assert result["verdict"] == "promote"
    assert result["promotion_authorized"] is False
    assert "none" in result["promotion_mechanism"].lower()


async def test_report_renders_without_error(async_db) -> None:
    """The CLI formatter must survive both the empty and the populated case."""
    empty = format_gate_report(await evaluate_ekf_calibration_gate(async_db))
    assert "VERDICT: stay_shadow" in empty
    assert "promotion authorized: False" in empty

    user = await _user(async_db, "ekfgate-fmt@test.com")
    await _seed_updates(async_db, user.id, n=40, nis=1.0)
    full = format_gate_report(await evaluate_ekf_calibration_gate(async_db))
    assert "VERDICT: promote" in full
    assert ARM_COVERAGE in full


# ── the anti-regression guard for the original defect ─────────────────────────


def _calls_by_name(source: str, func_name: str) -> int:
    """Count call sites of ``func_name``, ignoring its own definition and imports."""
    tree = ast.parse(source)
    return sum(
        1
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Name) and node.func.id == func_name)
            or (isinstance(node.func, ast.Attribute) and node.func.attr == func_name)
        )
    )


def test_the_production_calibration_feed_has_a_caller() -> None:
    """The defect this module fixes: a declared gate whose feed nothing invoked.

    ADR-0041's promotion evidence comes from production rows via
    ``build_ekf_calibration_records``. For a long time that function existed and was never
    called from anywhere, so the declared gate could not have run even in principle. If this
    fails again, the gate is decorative and every calibration claim is synthetic.
    """
    callers: dict[str, int] = {}
    for path in sorted((_REPO_ROOT / "app").rglob("*.py")):
        if path.name == "ekf_calibration_features.py":
            continue  # its own definition site
        n = _calls_by_name(path.read_text(encoding="utf-8"), _FEED_FUNC)
        if n:
            callers[str(path.relative_to(_REPO_ROOT))] = n

    assert callers, (
        f"{_FEED_FUNC} has no caller in app/ — ADR-0041's calibration gate reads production "
        "ekf_shadow_log rows through it, so with no caller the declared gate cannot run and "
        "every calibration number in the repo is synthetic."
    )
