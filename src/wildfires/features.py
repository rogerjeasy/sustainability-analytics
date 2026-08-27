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


def burn_rate(df: pd.DataFrame, area_col: str = "burnt_ha_total",
              size_col: str = "municipality_area_ha") -> pd.Series:
    """Share of a municipality's land area that burned in a given year.

    The parameter your notes flagged as missing. Requires municipality area,
    which comes from the GADM geometry in a metric CRS — see
    ``wildfires.merge.load_municipalities``.
    """
    return df[area_col] / df[size_col]


def log1p_safe(s: pd.Series) -> pd.Series:
    """log(1+x) that tolerates the zeros that dominate burnt-area columns."""
    return np.log1p(s.clip(lower=0))


def cause_shares(df: pd.DataFrame, cause_cols: list[str] | None = None) -> pd.DataFrame:
    """Convert the ICNF NInc_* cause counts into within-row shares.

    Counts scale with how many fires a municipality had; shares are what the
    'do demographics influence fire causes?' question actually asks about.
    """
    from wildfires.io import ICNF_CAUSE_COLS

    cols = ICNF_CAUSE_COLS if cause_cols is None else cause_cols
    present = [c for c in cols if c in df.columns]
    total = df[present].sum(axis=1)
    shares = df[present].div(total.replace(0, np.nan), axis=0)
    return shares.add_suffix("_share")


def fire_occurred(df: pd.DataFrame, threshold: float = 0.0) -> pd.Series:
    """Binary target for the ML chapter: did this municipality-year see fire?"""
    return (df["burnt_ha_total"].fillna(0) > threshold).astype(int)
