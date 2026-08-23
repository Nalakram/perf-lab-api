"""Daily wellness samples — first-class input to the readiness scalar (PDR-0005).

One row = one athlete's acute daily wellness on a given date from a given source
(a wearable provider's nightly pull, or a manual check-in). The readiness service
combines these acute signals with the engine's modeled fatigue/tissue state to
produce the single backend-owned readiness number.

``DailyCheckin`` is kept as an alias for the manual-entry framing; both names
refer to the same table.
"""

from datetime import date as date_cls
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base

if TYPE_CHECKING:
    from app.models.user import User


class WellnessSample(Base):
    __tablename__ = "wellness_samples"
    __table_args__ = (
        # One sample per athlete per day per source (idempotent ingestion).
        UniqueConstraint("user_id", "date", "source", name="uq_wellness_user_date_source"),
        # Mirrors alembic a039. Declared here too so a metadata-built schema (the test
        # fixture) enforces the same bound the migration does, rather than the constraint
        # existing only in production.
        CheckConstraint(
            "quality IS NULL OR (quality >= 0.0 AND quality <= 1.0)",
            name="ck_wellness_quality_0_1",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), index=True, nullable=False
    )
    date: Mapped[date_cls] = mapped_column(Date, index=True, nullable=False)

    # Provider / origin: "manual", "google_fit", "oura", "whoop", "polar", ...
    source: Mapped[str] = mapped_column(String(50), default="manual", nullable=False)

    # Acute wellness signals (all optional — sources vary in what they report).
    hrv_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    sleep_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    sleep_quality: Mapped[float | None] = mapped_column(Float, nullable=True)  # 0-100
    resting_hr: Mapped[float | None] = mapped_column(Float, nullable=True)
    soreness: Mapped[float | None] = mapped_column(Float, nullable=True)
    mood: Mapped[float | None] = mapped_column(Float, nullable=True)
    stress: Mapped[float | None] = mapped_column(Float, nullable=True)  # 0-10, higher = worse

    # When the reading was actually TAKEN, as opposed to when it reached us. `date` is a
    # calendar day and `created_at` is ingestion, so without this a 6am HRV and a 2pm one
    # are indistinguishable. Naive UTC, matching `created_at`. NULL means unknown — no row
    # is backfilled from `created_at`, because that would assert an ingestion time as a
    # measurement time.
    measured_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # 0..1 confidence in this reading, from the provider's own reliability signals (Oura
    # reports `low_battery_alert`, for instance). NULL means the source said nothing about
    # quality, which is not the same as saying the reading is perfect.
    quality: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Full source payload for provenance / future signals not yet modeled.
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    user: Mapped["User"] = relationship("User", back_populates="wellness_samples")


# Manual-entry framing of the same row (roadmap P5 names it DailyCheckin/WellnessSample).
DailyCheckin = WellnessSample
