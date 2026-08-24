"""Download additional Kaggle datasets into data/kaggle/.

Datasets pulled:
  open-powerlifting/powerlifting-database          -> data/kaggle/powerlifting/
  vlbthambawita/pmdata-a-sports-logging-dataset    -> data/kaggle/pmdata/
  aridoge13/high-intensity-strength-training-data  -> data/kaggle/hit-strength/

WHY THESE TWO WERE ADDED. Every other dataset on disk is objective or cross-sectional,
so the fields carrying the most modelling weight had no real source and were invented:
``soreness`` (the only EKF-assimilated wellness signal), ``session_rpe`` (required on
``WorkoutLog``), ``stress``, ``mood``, ``total_volume_load``, ``estimated_sets``.

  * **pmdata** supplies real subjective daily check-ins (soreness, stress, mood, fatigue,
    readiness, sleep) AND session RPE, per participant, over five months — and crucially
    the check-in and the session belong to the SAME person on the same day. Every other
    wellness/workout pairing in this repo is round-robin across unrelated subjects.
    Licensed CC BY-NC 4.0 — non-commercial. See ``app/scripts/load_pmdata.py``.
  * **hit-strength** supplies per-set weight/reps/RPE, which is what ``total_volume_load``
    and ``estimated_sets`` need. CC BY 4.0.

NOT fetchable here: SoccerMon (https://osf.io/uryz9/, two years of the same PMSys schema
from two elite squads) and ScopeSense (https://osf.io/v5acr/, 255 days, n=2) are hosted on
OSF, not Kaggle, so kagglehub cannot reach them. They are the natural scale-up once the
PMData mapping is proven; fetching them needs a separate downloader.

Uses kagglehub (reads KAGGLE_API_TOKEN from env). Loads .env automatically.
Idempotent: skips if destination already has files.

Run:
    python -m app.scripts.download_new_datasets
    python -m app.scripts.download_new_datasets --only pmdata
"""

from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path

# (kaggle slug, local directory name under data/kaggle/)
_DATASETS = [
    ("open-powerlifting/powerlifting-database", "powerlifting"),
    ("vlbthambawita/pmdata-a-sports-logging-dataset", "pmdata"),
    ("aridoge13/high-intensity-strength-training-data", "hit-strength"),
]


def _load_env() -> None:
    env_file = Path(".env")
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())


def main() -> None:
    ap = argparse.ArgumentParser(description="Download Kaggle datasets into data/kaggle/")
    ap.add_argument(
        "--only",
        action="append",
        default=None,
        metavar="NAME",
        help="Fetch only this local dataset name (repeatable). Default: all.",
    )
    args = ap.parse_args()

    selected = _DATASETS
    if args.only:
        wanted = set(args.only)
        known = {name for _, name in _DATASETS}
        unknown = wanted - known
        if unknown:
            raise SystemExit(f"Unknown dataset name(s) {sorted(unknown)}; known: {sorted(known)}")
        selected = [(slug, name) for slug, name in _DATASETS if name in wanted]

    _load_env()

    token = os.environ.get("KAGGLE_API_TOKEN")
    if not token:
        raise SystemExit("KAGGLE_API_TOKEN not set. Check .env or export it.")

    import kagglehub

    dest_base = Path("data/kaggle")
    dest_base.mkdir(parents=True, exist_ok=True)

    for dataset_slug, local_name in selected:
        dest = dest_base / local_name
        if dest.exists() and any(dest.rglob("*.csv")):
            print(f"  {local_name}: already present at data/kaggle/{local_name}/, skipping.")
            continue

        print(f"Downloading {dataset_slug} ...")
        cache_path = Path(kagglehub.dataset_download(dataset_slug))
        dest.mkdir(parents=True, exist_ok=True)

        copied = 0
        for src_file in cache_path.rglob("*"):
            if not src_file.is_file():
                continue
            rel = src_file.relative_to(cache_path)
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_file, target)
            copied += 1

        print(f"  -> data/kaggle/{local_name}/ ({copied} files copied)")

    print("Done.")


if __name__ == "__main__":
    main()
