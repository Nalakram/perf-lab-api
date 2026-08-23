"""Print what each shadow subsystem still needs before it could earn production authority.

Reads the declared criteria in ``app.logic.shadow_promotion_criteria`` — no database, no
network, no ML stack. Pure inspection of what the repo says about itself, which
``tests/test_shadow_promotion_criteria.py`` keeps honest: a claimed implementation must
resolve to a real symbol, and a shadow service on disk with no declared criteria fails CI.

Run:
    python -m app.scripts.shadow_promotion_status
    python -m app.scripts.shadow_promotion_status --json
    python -m app.scripts.shadow_promotion_status --verbose   # include the reasons

Always exits 0. Nothing here promotes anything, and "not promotable" is the expected state.
"""

from __future__ import annotations

import argparse
import json

from app.logic.shadow_promotion_criteria import (
    CRITERIA,
    CRITERIA_NAMES,
    format_summary,
    summary,
)


def _verbose_report() -> str:
    lines: list[str] = []
    for _key, sub in sorted(CRITERIA.items()):
        lines.append("")
        lines.append(f"{sub.subsystem}  [{sub.adr}]")
        lines.append(f"  module: {sub.service_module}")
        for name in CRITERIA_NAMES:
            c = sub.criterion(name)
            if c.implemented:
                lines.append(f"  [x] {name}: {c.implemented_by}")
                if c.note:
                    lines.append(f"        {c.note}")
            else:
                lines.append(f"  [ ] {name}: {c.note}")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Shadow-subsystem promotion readiness (declared criteria, no DB)."
    )
    ap.add_argument("--json", action="store_true", help="Emit the summary as JSON.")
    ap.add_argument(
        "--verbose", action="store_true", help="List every criterion with its reason."
    )
    args = ap.parse_args()

    if args.json:
        payload = {
            "summary": summary(),
            "subsystems": {
                key: {
                    "subsystem": sub.subsystem,
                    "adr": sub.adr,
                    "module": sub.service_module,
                    "criteria": {
                        name: {
                            "implemented": sub.criterion(name).implemented,
                            "implemented_by": sub.criterion(name).implemented_by,
                            "note": sub.criterion(name).note,
                        }
                        for name in CRITERIA_NAMES
                    },
                }
                for key, sub in sorted(CRITERIA.items())
            },
        }
        print(json.dumps(payload, indent=2))
        return

    print(format_summary())
    if args.verbose:
        print(_verbose_report())


if __name__ == "__main__":
    main()
