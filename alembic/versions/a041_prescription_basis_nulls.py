"""Heal NULL affects_prescription so the new prescription-basis predicate is safe.

``prescription_basis_filter()`` (app/repositories/benchmark_observation_repository.py)
starts requiring ``affects_prescription IS TRUE`` before an observation may size a
prescribed load. NULL is refused there on purpose: nobody stated whether the row may
drive a prescription, and absence of a statement is not permission.

That is only safe if no real measurement is sitting on a NULL. Two facts make it so:

* Migration a025 backfilled **every row that existed** when the column was added -
  ``source = 'workout_extraction'`` to false, everything else to true. There is no
  pre-a025 NULL population, so this predicate cannot make legacy measurements vanish.
* NULLs written *since* a025 come only from paths that bypass
  ``benchmark_service.create_observation`` (which defaults the flag to True). In this
  repo that is the corpus-ingest scripts - observed as ``synthetic:strength_standards``
  and ``kaggle:run_ww_2020`` rows. Those scripts now state the flag explicitly; this
  migration heals the rows they already wrote.

Semantics deliberately reuse a025's rule rather than inventing a second one: a
workout-derived row is not a prescription basis, anything else is a benchmark or manual
measurement and is. The conservative alternative - heal every NULL to false - was
rejected because it would strip the replay corpora of any e1RM basis and silently
degrade the replay harness, which is the "legacy measurements disappear" failure this
migration exists to avoid.

Backwards-compatible and re-runnable: it touches only rows that are still NULL.

Revision ID: a041_prescription_basis_nulls
Revises: a040_wellness_hrv_metric
Create Date: 2026-08-28
"""
from collections.abc import Sequence

from alembic import op

revision: str = "a041_prescription_basis_nulls"
down_revision: str | None = "a040_wellness_hrv_metric"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_T = "benchmark_observations"


def upgrade() -> None:
    # a025's rule, applied only to rows that never got a value.
    op.execute(
        f"""
        UPDATE {_T}
        SET affects_prescription = (source <> 'workout_extraction')
        WHERE affects_prescription IS NULL
        """
    )


def downgrade() -> None:
    # Not reversible in kind: the pre-migration state was "nobody had said", and that
    # is not recoverable from the healed value - a true here is indistinguishable from
    # a true a025 or create_observation wrote. Leaving the rows populated is the
    # correct no-op; nothing downstream requires the NULL back.
    pass
