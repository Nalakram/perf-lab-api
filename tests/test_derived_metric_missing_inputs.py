"""A missing measurement must not become a plausible number (goal invariant).

``relative_total`` divided a projected total by the athlete's bodyweight. When no
bodyweight was on file it substituted 75.0 kg and returned a real-looking ratio, which
``recompute_derived_metrics`` then persisted with ``confidence=1.0`` — the system was at
its most confident exactly where it had invented the divisor. That ratio is not cosmetic:
``candidate_library`` gates two complementary templates on ``pl_relative_total < 3.0``
(app/logic/candidate_library.py:351, :371), so a fabricated bodyweight selected which
session an athlete was prescribed, and it raised the ``pl_relative_total_low`` weak-point
flag (app/services/dashboard_service.py:321).

The honest behaviour already existed four lines away: every other unresolved context key
returns ``(None, [], f"missing input {key}")`` and the caller skips writing a snapshot.
``bodyweight_kg`` had its own branch with a ``continue`` that bypassed that check.
"""

import pytest

from app.logic.derived_metric_formulas import CUSTOM_FORMULAS, relative_total

# ── the formula itself ────────────────────────────────────────────────────────


def test_missing_bodyweight_is_not_computable() -> None:
    """No bodyweight on file must raise, never invent a divisor."""
    with pytest.raises(ValueError, match="bodyweight_kg"):
        relative_total({"pl_projected_total": 450.0, "bodyweight_kg": None})


def test_absent_bodyweight_key_is_not_computable() -> None:
    """A context that never supplied the key at all is equally not computable."""
    with pytest.raises(ValueError, match="bodyweight_kg"):
        relative_total({"pl_projected_total": 450.0})


def test_light_athlete_keeps_their_own_bodyweight() -> None:
    """A real measurement below the old 40 kg guard must survive unrewritten.

    Previously any bodyweight under 40.0 was silently replaced with 75.0, so a genuine
    38 kg athlete got 450/75 = 6.0 instead of their true 11.84 — a measured value
    overwritten with no flag.
    """
    assert relative_total(
        {"pl_projected_total": 450.0, "bodyweight_kg": 38.0}
    ) == pytest.approx(450.0 / 38.0)


def test_normal_bodyweight_is_unchanged() -> None:
    assert relative_total(
        {"pl_projected_total": 450.0, "bodyweight_kg": 90.0}
    ) == pytest.approx(5.0)


def test_nonpositive_bodyweight_is_not_computable() -> None:
    """Guards the division. The schema validates gt=0, so this is defence in depth."""
    with pytest.raises(ValueError, match="bodyweight_kg"):
        relative_total({"pl_projected_total": 450.0, "bodyweight_kg": 0.0})


def test_relative_total_is_still_registered() -> None:
    """The registry wiring is what the dashboard resolves against."""
    assert CUSTOM_FORMULAS["relative_total"] is relative_total


# ── the service-level contract ────────────────────────────────────────────────


def test_bodyweight_is_treated_like_every_other_missing_input() -> None:
    """``_compute_derived_value`` must report a missing bodyweight, not pass None through.

    The bug was structural: the ``bodyweight_kg`` branch ``continue``d before reaching the
    ``return None, [], f"missing input {key}"`` that every other unresolved key hits. A
    ``(None, ...)`` return makes ``recompute_derived_metrics`` skip the snapshot entirely,
    so no fabricated value is ever stored at confidence 1.0.
    """
    from app.services.dashboard_service import _compute_derived_value

    class _Def:
        formula_type = "custom_python_key"
        formula_config = {
            "function": "relative_total",
            "inputs": ["pl_projected_total", "bodyweight_kg"],
        }
        code = "pl_relative_total"

    val, obs_ids, err = _compute_derived_value(
        _Def(), {}, {"pl_projected_total": 450.0}, None
    )

    assert val is None, "a missing bodyweight must not produce a value"
    assert obs_ids == []
    assert err is not None and "bodyweight_kg" in err
