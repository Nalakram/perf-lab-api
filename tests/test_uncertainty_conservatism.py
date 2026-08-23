"""Low confidence may make a session more cautious - and off must change nothing.

Uncertainty was reported but never acted on: the twin could say "I am not sure about your
max strength" and then prescribe exactly as if it were sure. This is the lever, built the
way app/engine/feature_flags.py demands - a real OFF branch and a real ON branch a test can
tell apart. It shipped at "off"; as of 2026-08-23 it runs at "shadow", which reports what the
reduction would be without applying it. Moving to "on" remains a separate decision.

The cap is the lever rather than the load because prescription_service derives percentage,
kg and the load note from ``rpe_cap``; scaling the resolved kg afterwards would leave the
percentage and note describing a session that was not prescribed.
"""

import pytest

from app.engine import feature_flags
from app.logic.uncertainty_conservatism import (
    MIN_RPE_CAP,
    MODE_OFF,
    MODE_ON,
    MODE_SHADOW,
    RPE_REDUCTION,
    decide,
)


def _d(cap: float = 8.0, status: str | None = "insufficient", mode: str = MODE_ON):
    return decide(baseline_rpe_cap=cap, weakest_status=status, mode=mode)  # type: ignore[arg-type]


# ── the live setting must stay observational ──────────────────────────────────


def test_the_live_mode_is_observational_not_active() -> None:
    """The flag is at "shadow" by owner decision (2026-08-23), not at "on".

    Shadow reports what the reduction would be without applying it, so prescribed loads are
    unchanged. Moving to "on" changes the weight on the bar for real athletes and is a
    separate, deliberate decision - this test is what makes that decision visible in a diff
    rather than a one-character edit nobody reviews.
    """
    assert feature_flags.UNCERTAINTY_CONSERVATISM in {MODE_OFF, MODE_SHADOW}
    assert feature_flags.UNCERTAINTY_CONSERVATISM == MODE_SHADOW


def test_the_live_mode_does_not_move_any_cap() -> None:
    """Whatever the flag currently says, today's setting must not alter a prescription.

    Guards the promise made when shadow was enabled: observation only. If someone flips the
    constant to "on", this fails and the change cannot land unnoticed.
    """
    for status in ("insufficient", "provisional", "established", None):
        d = decide(
            baseline_rpe_cap=8.0,
            weakest_status=status,  # type: ignore[arg-type]
            mode=feature_flags.UNCERTAINTY_CONSERVATISM,
        )
        assert d.effective_rpe_cap == 8.0, f"{status} moved the cap under the live mode"
        assert d.applied is False


@pytest.mark.parametrize("status", ["insufficient", "provisional", "established", None])
def test_off_never_moves_the_cap(status: str | None) -> None:
    """Byte-identical to the pre-flag behaviour, whatever the confidence."""
    d = _d(status=status, mode=MODE_OFF)

    assert d.effective_rpe_cap == d.baseline_rpe_cap
    assert d.applied is False
    assert d.adjustment == 0.0


def test_an_unrecognised_mode_fails_closed() -> None:
    """A typo in config must not silently behave like "on"."""
    d = _d(mode="ON")  # not the lowercase literal

    assert d.applied is False
    assert d.effective_rpe_cap == d.baseline_rpe_cap
    assert "unrecognised mode" in d.reason


# ── on acts, proportionally ───────────────────────────────────────────────────


def test_insufficient_confidence_lowers_the_cap_most() -> None:
    d = _d(cap=8.0, status="insufficient", mode=MODE_ON)

    assert d.applied is True
    assert d.effective_rpe_cap == 8.0 - RPE_REDUCTION["insufficient"]
    assert d.adjustment < 0


def test_provisional_confidence_lowers_it_less() -> None:
    insufficient = _d(cap=8.0, status="insufficient", mode=MODE_ON)
    provisional = _d(cap=8.0, status="provisional", mode=MODE_ON)

    assert provisional.applied is True
    assert provisional.effective_rpe_cap > insufficient.effective_rpe_cap


def test_established_confidence_is_left_alone() -> None:
    """The rule only ever softens. Being sure is not licence to push harder."""
    d = _d(status="established", mode=MODE_ON)

    assert d.applied is False
    assert d.effective_rpe_cap == d.baseline_rpe_cap


def test_no_confidence_at_all_is_not_a_licence_either_way() -> None:
    """No state is no signal - not a reason to be aggressive, and no basis to reduce."""
    d = _d(status=None, mode=MODE_ON)

    assert d.applied is False
    assert d.effective_rpe_cap == d.baseline_rpe_cap
    assert "no capacity confidence" in d.reason


def test_the_cap_never_falls_below_a_productive_intensity() -> None:
    """An over-cautious plan that trains nothing is its own failure.

    Being unsure is a reason to back off, not a reason to stop driving adaptation.
    """
    d = _d(cap=6.2, status="insufficient", mode=MODE_ON)

    assert d.effective_rpe_cap >= MIN_RPE_CAP


def test_a_cap_already_at_the_floor_is_not_pushed_lower() -> None:
    d = _d(cap=MIN_RPE_CAP, status="insufficient", mode=MODE_ON)

    assert d.applied is False
    assert d.effective_rpe_cap == MIN_RPE_CAP
    assert "floor" in d.reason


# ── shadow describes without acting ───────────────────────────────────────────


def test_shadow_reports_the_reduction_but_prescribes_the_baseline() -> None:
    """The whole point of the middle state: observe the effect before it acts."""
    shadow = _d(cap=8.0, status="insufficient", mode=MODE_SHADOW)
    live = _d(cap=8.0, status="insufficient", mode=MODE_ON)

    assert shadow.applied is False
    assert shadow.effective_rpe_cap == 8.0
    assert shadow.adjustment == 0.0
    # ...but it says what ON would have done, so the two are comparable.
    assert f"{live.effective_rpe_cap:g}" in shadow.reason


def test_every_decision_explains_itself() -> None:
    for mode in (MODE_OFF, MODE_SHADOW, MODE_ON):
        for status in ("insufficient", "provisional", "established", None):
            d = decide(baseline_rpe_cap=8.0, weakest_status=status, mode=mode)  # type: ignore[arg-type]
            assert d.reason.strip(), f"{mode}/{status} gave no reason"


def test_the_rule_can_only_ever_soften() -> None:
    """No input may raise a cap. Pinned because the inverse is a different risk decision."""
    for mode in (MODE_OFF, MODE_SHADOW, MODE_ON):
        for status in ("insufficient", "provisional", "established", None):
            for cap in (6.0, 7.0, 8.0, 9.5):
                d = decide(baseline_rpe_cap=cap, weakest_status=status, mode=mode)  # type: ignore[arg-type]
                assert d.effective_rpe_cap <= cap, f"{mode}/{status}/{cap} raised the cap"
