"""The one place that answers "may this observation size a prescribed load?".

Two queries resolve an athlete's current e1RM, and ADR-0056 requires them to agree on
the number: ``prescription_service._current_e1rm_values`` (what load to prescribe) and
``state_service.prelog_e1rm_denominators`` (the ``I = load / e1RM_pre`` denominator for
dose intensity). They agreed on ``validity_status == 'valid'`` and nothing else, which
is how a row explicitly marked as unfit to prescribe from still sized the bar.

``affects_prescription`` existed to say exactly that and had **no reader anywhere in
``app/``** — it was set by ``benchmark_service.create_observation`` (defaulting True),
set to ``is_pr`` by ``state_service._extract_e1rm_observations`` under the comment "a
below-watermark set is history only - not even a prescription basis", exposed on the
request schema so a client can post ``false``, and then consulted by nobody. This module
is what makes that comment true.

Both call sites import ``prescription_basis_filter`` rather than restating the WHERE
clause, so a third reader cannot quietly reintroduce the divergence; the pairing is
pinned by ``tests/test_prescription_basis_authority.py``.
"""

from __future__ import annotations

from sqlalchemy import ColumnElement, and_

from app.models.benchmark_observation import BenchmarkObservation

#: The stored ``validity_status`` of an observation that has not been quarantined or
#: invalidated. A bare string on purpose: it is what a025's backfill and the column
#: default actually write. (``strength_evidence`` carries a richer purpose-specific
#: vocabulary — ``valid_for_capacity`` / ``valid_for_prescription`` — which nothing
#: persists yet; using those constants here would silently match zero rows.)
VALIDITY_VALID = "valid"


def prescription_basis_filter() -> ColumnElement[bool]:
    """SQL predicate: this observation may be used as a prescription basis.

    ``affects_prescription IS TRUE`` — deliberately not ``!= False``. NULL is refused,
    because NULL means no writer ever stated whether this row may drive a prescription,
    and absence of a statement must never be read as permission.

    Refusing NULL is safe for historical data specifically because migration a025
    backfilled every row that existed when the column was added: rows from
    ``workout_extraction`` to ``false``, every other row to ``true``. No legacy
    measurement is silently dropped by this predicate. Migration a041 heals any NULL
    written since a025 by a path that bypassed ``create_observation``.
    """
    return and_(
        BenchmarkObservation.validity_status == VALIDITY_VALID,
        BenchmarkObservation.affects_prescription.is_(True),
    )
