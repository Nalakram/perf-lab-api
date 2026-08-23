"""
Custom derived KPI calculators (formula_type == custom_python_key).

Context keys are resolved by the dashboard service (benchmark codes, nested KPIs,
profile fields).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

MILE_PER_400M = 1609.34 / 400.0


def hinshaw_fatigue_factor(ctx: Mapping[str, Any]) -> float:
    """
    Hinshaw-style 400m→mile gap: positive % means mile pace is slower than
    speed-endurance extrapolation from 400m (aerobic / durability deficit proxy).
    """
    t400 = float(ctx["run_400m_time"])
    t_mile = float(ctx["run_1mile_time"])
    if t400 <= 0 or t_mile <= 0:
        return 0.0
    predicted_mile = t400 * MILE_PER_400M
    return 100.0 * (t_mile / predicted_mile - 1.0)


def relative_total(ctx: Mapping[str, Any]) -> float:
    """Projected total per kg of the athlete's OWN bodyweight.

    Raises ``ValueError`` when bodyweight is absent rather than substituting a
    population figure. This previously read ``float(ctx.get("bodyweight_kg") or 0.0)``
    and then ``if bw < 40.0: bw = 75.0``, which did two dishonest things at once: it
    invented a 75 kg divisor for an athlete with no bodyweight on file, and it
    overwrote a *real* measurement below 40 kg with that same figure. The resulting
    ratio was persisted at ``confidence=1.0`` (dashboard_service.py:204 — nothing
    errored, so there was no note to lower it) and gates two complementary prescription
    templates at ``pl_relative_total < 3.0`` (candidate_library.py:351, :371). A
    fabricated divisor therefore chose an athlete's session.

    Raising is the correct signal here: ``_compute_derived_value`` maps a failed custom
    formula to ``(None, [], ...)`` and ``recompute_derived_metrics`` skips writing a
    snapshot for a ``None`` value, so the KPI is simply absent — which is what an
    unmeasured athlete's relative total actually is.
    """
    total = float(ctx["pl_projected_total"])
    raw_bw = ctx.get("bodyweight_kg")
    if raw_bw is None:
        raise ValueError("bodyweight_kg is required for relative_total and is missing")
    bw = float(raw_bw)
    if bw <= 0.0:
        raise ValueError(f"bodyweight_kg must be positive, got {bw!r}")
    return total / bw


def pull_support_balance(ctx: Mapping[str, Any]) -> float:
    """Simple balance score: pull strength vs isometric support."""
    pulls = max(0.0, float(ctx["gym_strict_pullup_max"]))
    hold_s = max(0.0, float(ctx["gym_ring_support_hold"]))
    denom = max(1.0, hold_s / 30.0)
    return pulls / denom


CUSTOM_FORMULAS: dict[str, Callable[[Mapping[str, Any]], float]] = {
    "hinshaw_fatigue_factor": hinshaw_fatigue_factor,
    "relative_total": relative_total,
    "pull_support_balance": pull_support_balance,
}
