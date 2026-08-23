"""Add `measured_at` and `quality` to wellness_samples (freshness + reliability).

`wellness_samples` recorded a day and an ingestion time, so a 6am HRV reading and a 2pm one
were indistinguishable, and the provider's own data-quality signals were captured into `raw`
and never read. With `source` now load-bearing for per-signal authority and baselines, the
next thing a resolver needs is *when* a reading was actually taken and *how much to trust it*.

Both are populated from documented Oura v2 sleep-document fields rather than inferred:
`bedtime_end` is when the sleep period — and so the HRV/resting-HR measurement window —
ended, and `low_battery_alert` is a first-party reliability flag.

Revision id kept under 32 characters: alembic's `alembic_version.version_num` column is
`varchar(32)` and a longer id fails at stamp time, not at authoring time.

Additive and nullable, so existing rows are untouched and every reader treats an absent value
as unknown rather than as a default. Nothing backfills: a historical row's measurement time is
genuinely unknown, and inventing one from `created_at` would assert an ingestion time as a
measurement time.

Revision ID: a039_wellness_measured_quality
Revises: a038_ekf_head_correction_replay
Create Date: 2026-08-23
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a039_wellness_measured_quality"
down_revision: str | None = "a038_ekf_head_correction_replay"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "wellness_samples",
        # Naive UTC, matching the column convention used by `created_at` here.
        sa.Column("measured_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "wellness_samples",
        sa.Column("quality", sa.Float(), nullable=True),
    )
    # 0..1, and only when present. A CHECK rather than app-side clamping: a provider
    # mapping that starts emitting 0-100 should fail loudly at the write, not silently
    # become a reading trusted a hundred times too much.
    op.create_check_constraint(
        "ck_wellness_quality_0_1",
        "wellness_samples",
        "quality IS NULL OR (quality >= 0.0 AND quality <= 1.0)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_wellness_quality_0_1", "wellness_samples", type_="check")
    op.drop_column("wellness_samples", "quality")
    op.drop_column("wellness_samples", "measured_at")
