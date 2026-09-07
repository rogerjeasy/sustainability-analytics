"""Derived variables for the statistical and ML chapters.

Anything a chapter computes that another chapter might also want belongs here,
so the two do not silently diverge.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def add_lags(
    df: pd.DataFrame,
    cols: list[str],
    lags: int | list[int] = 1,
    group: str = "dtcc",
    time: str = "year",
) -> pd.DataFrame:
    """Add within-municipality lagged copies of ``cols``.

    Grouping by municipality matters: without it, the lag of the first year of
    one municipality is silently taken from the last year of another.
    """
    lag_list = list(range(1, lags + 1)) if isinstance(lags, int) else list(lags)
    out = df.sort_values([group, time]).copy()
    for col in cols:
        for lag in lag_list:
            out[f"{col}_lag{lag}"] = out.groupby(group)[col].shift(lag)
    return out


def log1p_safe(s: pd.Series) -> pd.Series:
    """log(1+x) that tolerates the zeros that dominate burnt-area columns."""
    return np.log1p(s.clip(lower=0))


CAUSE_COLS = [
    "cause_natural", "cause_negligent", "cause_intentional",
    "cause_rekindle", "cause_unknown", "cause_uninvestigated",
]

BURNED_AREA_COL = "burned_ha_total"
IGNITED_AREA_COL = "burned_ha_total_ignited"


def cause_shares(df: pd.DataFrame, cause_cols: list[str] | None = None) -> pd.DataFrame:
    """Convert the ICNF cause counts into within-row shares.

    Counts scale with how many fires a municipality had; shares are what the
    'do demographics influence fire causes?' question actually asks about.

    Raises rather than returning an empty frame when the columns are absent. An
    earlier version filtered to whichever of its expected columns were present,
    so passing a panel that had been renamed returned ``(n, 0)`` silently — which
    propagates downstream as "no causes recorded" instead of "wrong frame".
    """
    cols = CAUSE_COLS if cause_cols is None else cause_cols
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(
            f"cause columns not found: {', '.join(missing)}. "
            f"Expected the built panel's names ({', '.join(cols)})."
        )
    total = df[cols].sum(axis=1)
    shares = df[cols].div(total.replace(0, np.nan), axis=0)
    return shares.add_suffix("_share")


def fire_occurred(df: pd.DataFrame, threshold: float = 0.0) -> pd.Series:
    """Binary target for the ML chapter: did this municipality-year see fire?

    Uses ``burned_ha_total``, which ICNF populates from 2017 onward only. Rows
    from the earlier era carry their area in ``burned_ha_total_ignited`` instead,
    and filling those nulls with zero would label sixteen years of fire history
    as fire-free — a silently wrong target rather than a missing value. Such rows
    are refused, so the caller decides explicitly what to do with them.
    """
    if BURNED_AREA_COL not in df.columns:
        raise ValueError(
            f"{BURNED_AREA_COL} not found. Expected the built panel's names; "
            "see docs/data_dictionary.md."
        )
    pre_2017 = df[BURNED_AREA_COL].isna()
    if IGNITED_AREA_COL in df.columns:
        pre_2017 &= df[IGNITED_AREA_COL].notna()
    if pre_2017.any():
        raise ValueError(
            f"{int(pre_2017.sum())} rows carry burned area under the pre-2017 "
            f"convention ({IGNITED_AREA_COL}) and none under {BURNED_AREA_COL}. "
            "Scoring them zero would mark burnt years as fire-free; filter to "
            "2017 onward, or score the two eras separately."
        )
    return (df[BURNED_AREA_COL].fillna(0) > threshold).astype(int)
