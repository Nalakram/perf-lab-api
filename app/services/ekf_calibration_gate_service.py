"""Run ADR-0041's declared EKF calibration gate against PRODUCTION shadow rows.

ADR-0041 makes NIS chi-squared consistency over the production ``ekf_shadow_log`` the
evidence that decides promote vs stay_shadow. Both halves of that already existed — the
math in ``app.ml.q10_confidence.ekf_calibration.calibration_report`` and the production
feed in ``app.analysis.feature_builders.ekf_calibration_features.build_ekf_calibration_records``
— but nothing ever called the feed. Grepping ``build_ekf_calibration_records`` across
``app/``, ``tests/`` and ``scripts/`` returned exactly one hit: its own ``def``. Every
calibration figure in this repo therefore came from an offline synthetic simulation, and no
check anywhere would notice a live estimator drifting.

This module is that missing caller.

Two things it deliberately does NOT do:

1. **It confers no authority.** There is no OFF/ON path for the EKF — ``app/engine/feature_flags.py``
   records that the five ``ENABLE_*`` booleans were deleted precisely because a flag read by
   no production code is a fictional promotion gate. So ``promotion_authorized`` is always
   ``False`` and a ``promote`` verdict means only "the calibration evidence would not block
   promotion", never "this is live".
2. **It does not pretend to be the whole gate.** ADR-0041 names two arms: NIS chi-squared and
   interval coverage. Production rows store ``nis``/``n_obs`` but not the predictive std, so
   coverage is structurally unmeasurable here and ``calibration_report`` silently skips the
   ``nan`` levels. A ``promote`` from this gate is therefore a *partial* pass. The result
   states that in ``arms_evaluated`` / ``arms_not_evaluated`` rather than letting a caller
   read one arm's verdict as both.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

# ADR-0041's two declared gate arms. Only the first is computable from production rows.
ARM_NIS = "nis_chi2"
ARM_COVERAGE = "interval_coverage"

# Why the coverage arm cannot run against the log, stated once.
COVERAGE_UNAVAILABLE = (
    "interval coverage needs the per-observation predictive std, which ekf_shadow_log does "
    "not store; only the replay harness holds it"
)

VERDICT_UNAVAILABLE = "unavailable"


async def evaluate_ekf_calibration_gate(
    db: AsyncSession,
    *,
    user_id: int | None = None,
) -> dict[str, Any]:
    """Evaluate the NIS arm of ADR-0041's gate over real ``ekf_shadow_log`` rows.

    Pass ``user_id`` to scope to one athlete; omit it for the fleet-wide view, which is the
    scope a promotion decision would actually need. Read-only: it issues one SELECT and
    changes nothing.

    Never raises for the ordinary "no data yet" case — an empty log yields a
    ``stay_shadow`` verdict blocked on ``insufficient updates``, which is the honest answer.
    """
    # Lazy import, matching shadow_summary_service._ekf_section. The ML stack transitively
    # pulls pandas, which is absent from the lean production image; importing it at module
    # load broke app startup and every deploy from 2026-07-07. Keep this inside the function.
    try:
        from app.analysis.feature_builders.ekf_calibration_features import (
            build_ekf_calibration_records,
        )
        from app.ml.q10_confidence.ekf_calibration import (
            MIN_UPDATES,
            NIS_RATIO_HI,
            NIS_RATIO_LO,
            calibration_report,
        )
    except ImportError as exc:  # pragma: no cover - depends on the deployed image
        # Report the gate as unavailable rather than as passing or failing. A calibration
        # instrument that silently degrades to "fine" is worse than no instrument.
        return {
            "scope": _scope(user_id),
            "gate": "adr_0041_ekf_calibration",
            "available": False,
            "unavailable_reason": f"offline ML stack not importable: {exc}",
            "verdict": VERDICT_UNAVAILABLE,
            "promotion_authorized": False,
        }

    records = await build_ekf_calibration_records(db, user_id)
    report = calibration_report(records)

    return {
        "scope": _scope(user_id),
        "gate": "adr_0041_ekf_calibration",
        "available": True,
        "unavailable_reason": None,
        # What the verdict was actually computed from.
        "arms_evaluated": [ARM_NIS],
        "arms_not_evaluated": {ARM_COVERAGE: COVERAGE_UNAVAILABLE},
        "n_updates": int(report.nis.get("n_updates", 0)),
        "dof": int(report.nis.get("dof", 0)),
        "min_updates_required": MIN_UPDATES,
        "nis_ratio_band": [NIS_RATIO_LO, NIS_RATIO_HI],
        "nis": report.nis,
        "verdict": report.verdict,
        "blocking_reasons": list(report.reasons),
        "warnings": list(report.warnings),
        # The EKF has no OFF/ON path, so no verdict from here can promote anything. Saying
        # so in the payload keeps a `promote` from being read as "it went live".
        "promotion_authorized": False,
        "promotion_mechanism": (
            "none - the EKF has no production OFF/ON path; see app/engine/feature_flags.py"
        ),
    }


def _scope(user_id: int | None) -> str:
    return "fleet" if user_id is None else f"user:{user_id}"


def format_gate_report(result: dict[str, Any]) -> str:
    """Render a gate result as plain text for a CLI or a log line."""
    lines = [
        f"EKF calibration gate (ADR-0041) - scope: {result['scope']}",
    ]
    if not result.get("available"):
        lines.append(f"  UNAVAILABLE: {result.get('unavailable_reason')}")
        return "\n".join(lines)

    # Annotated rather than inferred: `result` is dict[str, Any], so an unannotated
    # `result.get("nis") or {}` infers dict[Unknown, Unknown] and every downstream .get()
    # trips the strict-pyright gate on the runtime request path.
    nis: dict[str, Any] = result.get("nis") or {}
    ratio: Any = nis.get("ratio")
    band: list[Any] = result["nis_ratio_band"]
    lo, hi = band[0], band[1]
    lines.append(
        f"  updates: {result['n_updates']} (need {result['min_updates_required']})"
        f"   dof: {result['dof']}"
    )
    lines.append(
        f"  NIS ratio: {'n/a' if ratio is None else f'{ratio:.3f}'}"
        f"   band: [{lo}, {hi}]"
        f"   within chi2: {nis.get('within_chi2')}"
    )
    arms: list[str] = result["arms_evaluated"]
    lines.append(f"  arms evaluated: {', '.join(arms)}")
    skipped: dict[str, str] = result["arms_not_evaluated"]
    for arm, why in skipped.items():
        lines.append(f"  arm NOT evaluated: {arm} - {why}")
    lines.append(f"  VERDICT: {result['verdict']}")
    reasons: list[str] = result["blocking_reasons"]
    for reason in reasons:
        lines.append(f"    blocked by: {reason}")
    warns: list[str] = result["warnings"]
    for warn in warns:
        lines.append(f"    warning: {warn}")
    lines.append(f"  promotion authorized: {result['promotion_authorized']}")
    lines.append(f"    {result['promotion_mechanism']}")
    return "\n".join(lines)
