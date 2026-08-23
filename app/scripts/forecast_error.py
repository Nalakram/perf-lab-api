"""Report how wrong the twin's own session forecasts were.

Compares `why.expected_outcomes` recorded on completed prescriptions against what the
athlete's state actually did. Read-only, and it authorizes nothing: a bias figure here is
evidence, not a licence to adjust the model.

Run (against a local DB):
    $env:DATABASE_URL = "postgresql+asyncpg://perfuser:perfpass123@localhost:5432/perflab"
    python -m app.scripts.forecast_error
    python -m app.scripts.forecast_error --user-id 3 --json

Always exits 0. "Nothing scoreable yet" is the expected state until prescriptions carrying
forecasts have been completed and followed by a state snapshot.
"""

from __future__ import annotations

import argparse
import asyncio
import json

from app.core.db import AsyncSessionLocal
from app.services.forecast_scoring_service import format_report, score_forecasts


async def _run(*, user_id: int | None, as_json: bool, limit: int) -> None:
    async with AsyncSessionLocal() as db:
        result = await score_forecasts(db, user_id=user_id, limit=limit)
    print(json.dumps(result, indent=2, default=str) if as_json else format_report(result))


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Forecast error vs realized state for completed prescriptions."
    )
    ap.add_argument("--user-id", type=int, default=None, help="Scope to one athlete.")
    ap.add_argument("--limit", type=int, default=200, help="Most recent sessions to examine.")
    ap.add_argument("--json", action="store_true", help="Emit the raw result as JSON.")
    args = ap.parse_args()
    asyncio.run(_run(user_id=args.user_id, as_json=args.json, limit=args.limit))


if __name__ == "__main__":
    main()
