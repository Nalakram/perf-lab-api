"""Promotion criteria must be declared as checkable data, not ADR prose.

The project requires every advanced estimator to have explicit calibration, replay,
promotion, canary, rollback and recertification criteria. Those lived only in ADRs, and
prose cannot be checked — which is exactly how ADR-0041's calibration gate came to sit with
zero callers, and how four ADRs came to describe canary/rollback machinery nobody wrote.
The real state had to be rediscovered by grep.

These tests keep ``shadow_promotion_criteria`` honest in the two directions it can rot:

- **Aspiration** — a criterion marked done by writing a plausible dotted path that resolves
  to nothing. Every ``implemented_by`` is imported here.
- **Silence** — a new shadow subsystem landing with no declared promotion story at all.
  The registry is checked against what is actually on disk.
"""

import importlib
from pathlib import Path

import pytest

from app.logic.shadow_promotion_criteria import (
    CRITERIA,
    CRITERIA_NAMES,
    Criterion,
    SubsystemCriteria,
    format_summary,
    summary,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SHADOW_SERVICES = sorted((_REPO_ROOT / "app" / "services").glob("*_shadow_service.py"))


def _all_criteria() -> list[tuple[str, str, Criterion]]:
    return [
        (key, name, sub.criterion(name))
        for key, sub in CRITERIA.items()
        for name in CRITERIA_NAMES
    ]


# ── the registry matches reality ──────────────────────────────────────────────


def test_every_shadow_service_on_disk_declares_its_promotion_criteria() -> None:
    """A new shadow subsystem must state what would promote it before it can land.

    This is the guard that matters most. Seven permanent shadow demonstrations is what
    happens when a subsystem can ship with telemetry and no stated path out of shadow.
    """
    on_disk = {p.stem for p in _SHADOW_SERVICES}
    declared = set(CRITERIA)

    assert on_disk == declared, (
        "shadow_promotion_criteria.CRITERIA is out of sync with app/services/*_shadow_service.py.\n"
        f"  undeclared on disk: {sorted(on_disk - declared)}\n"
        f"  declared but gone:  {sorted(declared - on_disk)}\n"
        "A shadow estimator with no declared promotion criteria becomes a permanent demo."
    )


def test_the_glob_still_finds_the_shadow_services() -> None:
    """Guards the test above: an empty glob would make it vacuously pass."""
    assert len(_SHADOW_SERVICES) >= 5, [p.name for p in _SHADOW_SERVICES]


def test_each_declared_service_module_is_importable() -> None:
    for key, sub in CRITERIA.items():
        # import_module raises on a bad path; assert the module object to keep this a
        # real assertion rather than a bare expression statement.
        assert importlib.import_module(sub.service_module) is not None, (
            f"{key}: {sub.service_module}"
        )


# ── no aspiration: a claimed implementation must exist ────────────────────────


@pytest.mark.parametrize(
    ("key", "name", "criterion"),
    [(k, n, c) for k, n, c in _all_criteria() if c.implemented],
    ids=lambda v: v if isinstance(v, str) else "",
)
def test_a_claimed_implementation_resolves_to_a_real_symbol(
    key: str, name: str, criterion: Criterion
) -> None:
    """Marking a criterion done requires a symbol that actually imports.

    Without this, "implemented" is just a string someone typed, which is the same failure
    mode as an ADR describing a gate that was never built.
    """
    assert criterion.implemented_by is not None
    module_path, _, symbol = criterion.implemented_by.rpartition(".")
    assert module_path, f"{key}.{name}: not a dotted path: {criterion.implemented_by!r}"

    module = importlib.import_module(module_path)
    assert hasattr(module, symbol), (
        f"{key}.{name} claims {criterion.implemented_by!r} but {module_path} has no {symbol!r}"
    )


# ── no silence: an unimplemented criterion must say why ───────────────────────


@pytest.mark.parametrize(
    ("key", "name", "criterion"),
    [(k, n, c) for k, n, c in _all_criteria() if not c.implemented],
    ids=lambda v: v if isinstance(v, str) else "",
)
def test_an_unimplemented_criterion_states_a_reason(
    key: str, name: str, criterion: Criterion
) -> None:
    """"Not done" always comes with what is missing, never a blank."""
    assert criterion.note.strip(), f"{key}.{name} is unimplemented with no reason given"


def test_every_criterion_name_is_a_real_field() -> None:
    """CRITERIA_NAMES and the dataclass fields must not drift apart."""
    fields = SubsystemCriteria.__dataclass_fields__
    for name in CRITERIA_NAMES:
        assert name in fields, f"CRITERIA_NAMES lists {name!r}, which is not a field"
    for key, sub in CRITERIA.items():
        for name in CRITERIA_NAMES:
            assert isinstance(sub.criterion(name), Criterion), f"{key}.{name}"


# ── the registry reports the real state, not a flattering one ─────────────────


def test_the_ekf_calibration_entry_points_at_the_gate_that_actually_runs() -> None:
    """The one implemented criterion in the repo, pinned to its implementation."""
    ekf = CRITERIA["ekf_shadow_service"]

    assert ekf.calibration.implemented
    assert "ekf_calibration_gate_service" in (ekf.calibration.implemented_by or "")
    # ADR-0041 names two arms and only one is computable from production rows; the note
    # must keep saying so, or a reader takes a partial pass for a full one.
    assert "PARTIAL" in ekf.calibration.note


def test_nothing_is_fully_promotable_yet() -> None:
    """A canary in the registry itself.

    If this ever fails, a subsystem has genuinely acquired all six criteria — at which point
    the promotion decision is a human one, and this test should be updated deliberately
    rather than a subsystem quietly acquiring authority.
    """
    assert summary()["fully_promotable"] == []


def test_summary_counts_match_the_registry() -> None:
    s = summary()

    assert s["subsystems"] == len(CRITERIA)
    assert s["total"] == len(CRITERIA) * len(CRITERIA_NAMES)
    assert s["implemented"] == sum(c.implemented_count for c in CRITERIA.values())
    by = s["by_criterion"]
    assert isinstance(by, dict)
    assert set(by) == set(CRITERIA_NAMES)


def test_format_summary_renders_every_subsystem() -> None:
    text = format_summary()

    for key in CRITERIA:
        assert key in text
    assert "implemented:" in text
