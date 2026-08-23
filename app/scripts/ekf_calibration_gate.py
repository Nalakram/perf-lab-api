"""Run ADR-0041's EKF calibration gate against production shadow rows.

The gate ADR-0041 declares — NIS chi-squared consistency over real ``ekf_shadow_log`` rows
— had no runner. The math and the production feed both existed;
``build_ekf_calibration_records`` simply had no caller anywhere, so every calibration figure
in the repo came from an offline synthetic simulation and nothing would have noticed a live
estimator drifting.

This is the runner. It is read-only: one SELECT, no writes, no state change, and it cannot
promote anything — the EKF has no production OFF/ON path (see ``app/engine/feature_flags.py``).

Run (against a local DB):
    $env:DATABASE_URL = "postgresql+asyncpg://perfuser:perfpass123@localhost:5432/perflab"
    python -m app.scripts.ekf_calibration_gate
    python -m app.scripts.ekf_calibration_gate --user-id 3

Exit codes:
    0  the gate ran and reported a verdict (including ``stay_shadow``, the expected state)
    1  --require-promotable was passed and the verdict was not ``promote``
    2  the gate could not run at all (offline ML stack missing from the image)

``stay_shadow`` is not a failure — it is the correct answer for an un-promoted estimator, so
the default exit code is 0. Use ``--require-promotable`` only where you actually intend a
non-promotable verdict to fail a pipeline.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from app.core.db import AsyncSessionLocal
from app.services.ekf_calibration_gate_service import (
    VERDICT_UNAVAILABLE,
    evaluate_ekf_calibration_gate,
    format_gate_report,
)


async def _run(*, user_id: int | None, as_json: bool, require_promotable: bool) -> int:
    async with AsyncSessionLocal() as db:
        result = await evaluate_ekf_calibration_gate(db, user_id=user_id)

    if as_json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(format_gate_report(result))

    if result["verdict"] == VERDICT_UNAVAILABLE:
        return 2
    if require_promotable and result["verdict"] != "promote":
        return 1
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Run ADR-0041's EKF calibration gate over production ekf_shadow_log rows."
    )
    ap.add_argument(
        "--user-id",
        type=int,
        default=None,
        help="Scope to one athlete. Omit for the fleet-wide view a promotion would need.",
    )
    ap.add_argument("--json", action="store_true", help="Emit the raw result as JSON.")
    ap.add_argument(
        "--require-promotable",
        action="store_true",
        help="Exit 1 unless the verdict is 'promote'. Off by default: stay_shadow is the "
        "correct state for an un-promoted estimator, not a failure.",
    )
    args = ap.parse_args()
    sys.exit(
        asyncio.run(
            _run(
                user_id=args.user_id,
                as_json=args.json,
                require_promotable=args.require_promotable,
            )
        )
    )


if __name__ == "__main__":
    main()
