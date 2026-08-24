"""Add `hrv_metric` to wellness_samples so unlike HRV metrics are never pooled.

`hrv_ms` is documented as "rMSSD-style HRV (ms)" but the column records only a number, not
which HRV metric produced it. Different devices report different metrics from the same
inter-beat intervals: Oura, Whoop and Garmin report rMSSD, while Apple Watch reports SDNN —
HealthKit exposes only `HKQuantityTypeIdentifierHeartRateVariabilitySDNN`. SDNN typically
runs 10-25% higher than rMSSD computed from the same data, so the two are not interchangeable
and a mean over both describes no instrument.

Without a discriminator that failure is silent. `readiness_service._baselines` averages a
28-day window and `wellness_modifier` z-scores today's value against it using an anchor of
60.0 ms tuned for rMSSD, so an SDNN reading would be scored against an rMSSD baseline and the
athlete's deviation measured against a number no device ever produced. This is the same class
of defect a038's sibling work closed for `source` (PR #211): comparing unlike things.

Backfill IS applied here, unlike a039's deliberate refusal, because this is a deduction rather
than an invention. Oura's v2 `average_hrv` — the only field `app/integrations/oura.py` maps
into `hrv_ms` for `source='oura'` — is an average of 5-minute rMSSD windows across sleep, a
documented vendor property confirmed against Oura's API docs and an independent validation
study. Stamping those rows 'rmssd' records what the vendor already determined; leaving them
NULL would restart every existing Oura athlete's personal baseline for no informational gain.
The known edge is that `source` is a free string, so a hand-entered row claiming 'oura' is
also stamped — which is still correct, since a number copied off an Oura ring is still rMSSD.

Every other historical row stays NULL: those sources genuinely never declared a metric, and
NULL is read as "unknown", never as "assumed rMSSD".

Revision id kept under 32 characters: alembic's `alembic_version.version_num` column is
`varchar(32)` and a longer id fails at stamp time, not at authoring time.

Revision ID: a040_wellness_hrv_metric
Revises: a039_wellness_measured_quality
Create Date: 2026-08-24
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a040_wellness_hrv_metric"
down_revision: str | None = "a039_wellness_measured_quality"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "wellness_samples",
        sa.Column("hrv_metric", sa.String(length=16), nullable=True),
    )
    # A closed vocabulary enforced at the write. A provider mapping that starts emitting an
    # unrecognized label should fail loudly rather than silently create a third baseline
    # bucket that quietly halves every athlete's usable history.
    op.create_check_constraint(
        "ck_wellness_hrv_metric_vocab",
        "wellness_samples",
        "hrv_metric IS NULL OR hrv_metric IN ('rmssd', 'sdnn')",
    )
    # Deduced from a documented vendor property, not inferred from the value — see docstring.
    op.execute(
        "UPDATE wellness_samples SET hrv_metric = 'rmssd' "
        "WHERE source = 'oura' AND hrv_ms IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_constraint("ck_wellness_hrv_metric_vocab", "wellness_samples", type_="check")
    op.drop_column("wellness_samples", "hrv_metric")
