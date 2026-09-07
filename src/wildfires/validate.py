"""Contract checks the panels must satisfy before anyone analyses them.

The point is to fail loudly. A panel with a silently empty column or a merge that
multiplied rows produces confident, wrong answers downstream.

The tricky case is a column that is *legitimately* empty. ICNF changed its
burned-area convention at 2017 with no overlap year, so the panels carry two
mutually exclusive families of burned-area columns:

    burned_ha_*          the ``_NoConcelho`` convention, populated 2017-2025
    burned_ha_*_ignited  the pre-2017 convention, populated 2001-2016

Across the fire panel's 2001-2025 span both families have data, so nothing there
is exempt: an all-null burned-area column is a real regression. Inside the
analysis panel's 2019-2024 window the pre-2017 family contributes no rows at all,
so every ``*_ignited`` column is 100% null in a *correct* panel and must be
exempted, or the build would refuse to emit good data.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

EXPECTED_PANEL_ROWS = 1668
EXPECTED_MUNICIPALITIES = 278
EXPECTED_PANEL_YEARS = [2019, 2020, 2021, 2022, 2023, 2024]

_IGNITED_ERA = "ICNF's pre-2017 convention contributes no rows to 2019-2024"

# Columns allowed to be entirely null in the *analysis* panel, with the reason.
KNOWN_SPARSE = {
    "burned_ha_total_ignited": _IGNITED_ERA,
    "burned_ha_forest_ignited": _IGNITED_ERA,
    "burned_ha_shrub_ignited": _IGNITED_ERA,
    "burned_ha_agric_ignited": _IGNITED_ERA,
    "burn_rate_ignited": f"derived from the ignited columns, so {_IGNITED_ERA}",
}

# The fire panel spans both conventions, so nothing in it is exempt.
FIRE_PANEL_KNOWN_SPARSE: dict[str, str] = {}


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    detail: str


def _key_checks(panel: pd.DataFrame) -> list[Check]:
    duplicated = int(panel.duplicated(["dtcc", "year"]).sum())
    return [Check(
        name="(dtcc, year) is unique",
        passed=duplicated == 0,
        detail=f"{duplicated} duplicate keys",
    )]


def _null_checks(panel: pd.DataFrame, allowed: dict[str, str]) -> list[Check]:
    empty = [c for c in panel.columns if panel[c].isna().all() and c not in allowed]
    return [Check(
        name="no all-null column",
        passed=not empty,
        detail="none" if not empty else f"empty: {', '.join(empty)}",
    )]


def validate_panel(panel: pd.DataFrame) -> list[Check]:
    """Contract for the 2019-2024 joined panel."""
    checks = _key_checks(panel)
    checks.append(Check(
        name=f"row count is {EXPECTED_PANEL_ROWS}",
        passed=len(panel) == EXPECTED_PANEL_ROWS,
        detail=f"{len(panel)} rows (expected {EXPECTED_PANEL_ROWS})",
    ))
    checks.append(Check(
        name=f"{EXPECTED_MUNICIPALITIES} municipalities",
        passed=panel.dtcc.nunique() == EXPECTED_MUNICIPALITIES,
        detail=f"{panel.dtcc.nunique()} distinct dtcc",
    ))
    years = sorted(int(y) for y in panel.year.unique())
    checks.append(Check(
        name="years are 2019-2024",
        passed=years == EXPECTED_PANEL_YEARS,
        # int() rather than the raw numpy scalars, whose repr would leak
        # "np.int64(2019)" into the rendered report.
        detail=", ".join(str(y) for y in years),
    ))
    checks.extend(_null_checks(panel, allowed=KNOWN_SPARSE))
    return checks


def validate_fire_panel(panel: pd.DataFrame) -> list[Check]:
    """Contract for the 2001-2025 fire panel."""
    checks = _key_checks(panel)
    checks.append(Check(
        name="spans 2001-2025",
        passed=panel.year.min() == 2001 and panel.year.max() == 2025,
        detail=f"{int(panel.year.min())}-{int(panel.year.max())}",
    ))
    checks.append(Check(
        name="carries no demography",
        passed="pop_total" not in panel.columns,
        detail="clean" if "pop_total" not in panel.columns else "pop_total leaked in",
    ))
    checks.extend(_null_checks(panel, allowed=FIRE_PANEL_KNOWN_SPARSE))
    return checks


def render_report(results: dict[str, list[Check]]) -> str:
    """Render the checks as Markdown for data/processed/validation_report.md."""
    lines = [
        "# Panel validation report",
        "",
        f"Generated {date.today().isoformat()}.",
        "",
    ]
    for dataset, checks in results.items():
        failed = sum(not c.passed for c in checks)
        lines += [f"## {dataset}", "",
                  f"{len(checks) - failed}/{len(checks)} checks passed.", "",
                  "| Check | Result | Detail |", "|---|---|---|"]
        for check in checks:
            lines.append(
                f"| {check.name} | {'PASS' if check.passed else 'FAIL'} | {check.detail} |"
            )
        lines.append("")

    lines += ["## Known and expected gaps", "",
              "Empty in the analysis panel by construction, not by failure:", ""]
    for column, reason in KNOWN_SPARSE.items():
        lines.append(f"- `{column}` — {reason}")
    lines += ["- `pop_density` — INE flags a break in series at 2021 "
              "(Censos 2021 re-basing). Values are as published; see "
              "`data/processed/series_breaks.csv`.",
              "- EFFIS columns are null wherever no fire large enough to be mapped "
              "was resolved in that municipality-year. That is an absence of *mapped* "
              "fire, not an absence of fire: most such rows still carry ICNF ignitions. "
              "Do not read these nulls as zeros.", ""]
    return "\n".join(lines)


def null_rate_table(panel: pd.DataFrame) -> pd.DataFrame:
    """Per-column null rate, for the report's appendix."""
    return (
        panel.isna().mean().mul(100).round(2)
        .rename("null_pct").reset_index().rename(columns={"index": "column"})
        .sort_values("null_pct", ascending=False).reset_index(drop=True)
    )


def render_null_rates(panel: pd.DataFrame) -> str:
    """Markdown for the null-rate appendix.

    Written by hand rather than via DataFrame.to_markdown, which needs `tabulate` —
    a dependency this project does not carry and does not need for one table.
    """
    table = null_rate_table(panel)
    lines = ["| Column | Null % |", "|---|---|"]
    lines += [f"| `{row.column}` | {row.null_pct:.2f} |" for row in table.itertuples()]
    return "\n".join(lines)
