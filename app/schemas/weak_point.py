"""Request/response schemas for the weak-point routes.

Moved verbatim from ``app/api/v1/weak_points.py`` so the service layer can accept
``WeakPointPatch`` without importing from the HTTP module.

Class names, field order, defaults, and constraints are frozen. The OpenAPI
component keys derive from the class names and the ``required`` array preserves
declaration order, so any edit here is a public-contract change and will be
caught by ``app.scripts.export_openapi --check``.
"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class WeakPointOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tag: str
    source: str          # WeakPointSource value as string
    confidence: float
    note: str | None
    detected_at: datetime
    resolved_at: datetime | None
    is_active: bool


class WeakPointPatch(BaseModel):
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    note: str | None = None
    resolved_at: datetime | None = None   # pass datetime to resolve; pass null to re-open
