#!/usr/bin/env python
"""Build every interim and processed dataset from data/raw.

    make data                                    run all stages, then validate
    python scripts/build_data.py --stage ine     run one stage

Stages are ordered and each writes exactly one artifact, so a failure part-way
through does not discard completed work.
"""

from __future__ import annotations

import argparse
import sys

import pandas as pd

from wildfires.config import PATHS, project_root
from wildfires.merge import build_fire_panel, build_panel, build_typology
from wildfires.pipeline import build_effis, build_effis_subset, build_icnf, build_ine
from wildfires.validate import (
    render_null_rates,
    render_report,
    validate_fire_panel,
    validate_panel,
)

STAGES = {
    # effis_subset runs first: it is what makes the pipeline reproducible from
    # data/raw alone, and every later EFFIS step reads the file it writes.
    "effis_subset": build_effis_subset,
    "icnf": build_icnf,
    "ine": build_ine,
    "effis": build_effis,
    "fire_panel": build_fire_panel,
    "panel": build_panel,
    "typology": build_typology,
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=sorted(STAGES),
                        help="run a single stage instead of all of them")
    parser.add_argument("--skip-validate", action="store_true",
                        help="skip the contract checks (not recommended)")
    args = parser.parse_args()

    root = project_root()
    names = [args.stage] if args.stage else list(STAGES)

    for name in names:
        print(f"[BUILD   ] {name}", flush=True)
        frame = STAGES[name](save=True)
        print(f"           {len(frame):,} rows x {len(frame.columns)} columns", flush=True)

    if args.stage or args.skip_validate:
        return 0

    missing = [n for n in ("panel", "fire_panel") if not PATHS["processed"][n].exists()]
    if missing:
        print(f"Cannot validate: {missing} were not written.")
        return 1

    # Validate the artifacts that were just written rather than rebuilding them.
    # Re-calling build_panel() here would repeat the EFFIS spatial join, the most
    # expensive step in the pipeline, two more times.
    print("\n[VALIDATE]", flush=True)
    panel = pd.read_parquet(PATHS["processed"]["panel"])
    fire_panel = pd.read_parquet(PATHS["processed"]["fire_panel"])
    results = {
        "panel_municipality_year": validate_panel(panel),
        "fire_panel_municipality_year": validate_fire_panel(fire_panel),
    }
    for dataset, checks in results.items():
        for check in checks:
            mark = "PASS" if check.passed else "FAIL"
            print(f"           {mark} {dataset}: {check.name} — {check.detail}")

    report = render_report(results)
    appendix = ["## Null rates — panel", "", render_null_rates(panel)]
    target = PATHS["processed"]["validation_report"]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(report + "\n" + "\n".join(appendix) + "\n", encoding="utf-8")
    print(f"\n           wrote {target.relative_to(root)}")

    failed = [c for checks in results.values() for c in checks if not c.passed]
    if failed:
        print(f"\n{len(failed)} contract check(s) failed. The panel is not usable as built.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
