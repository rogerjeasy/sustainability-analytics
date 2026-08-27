"""Normalisation helpers shared by the cleaning notebook and the merge step."""

from __future__ import annotations

import unicodedata

import pandas as pd


def normalise_name(s: pd.Series) -> pd.Series:
    """Casefold, strip accents and collapse whitespace in a place-name column.

    Portuguese place names arrive inconsistently across sources: GADM writes
    ``"CastelodePaiva"`` where ICNF writes ``"Castelo de Paiva"``, and accents
    differ by encoding. Use this for *diagnostics and fallback matching only* —
    the authoritative join key is the DTCC code, because 308 municipalities
    share only 306 distinct names.
    """
    out = s.astype("string").str.strip()
    out = out.map(
        lambda v: unicodedata.normalize("NFKD", v).encode("ascii", "ignore").decode()
        if pd.notna(v) else v
    )
    return out.str.lower().str.replace(r"\s+", " ", regex=True)


def normalise_dtcc(s: pd.Series) -> pd.Series:
    """Coerce a municipality code column to the canonical 4-character form."""
    return (
        pd.to_numeric(s, errors="coerce")
        .astype("Int64")
        .astype("string")
        .str.zfill(4)
    )


def apply_size_floor(df: pd.DataFrame, area_col: str = "AREA_HA", min_ha: float | None = None):
    """Drop fires below the comparability floor.

    EFFIS lowered its minimum mapped fire size around 2020 — the median
    Portuguese fire falls from 131 ha to 5 ha purely from that detection change.
    Any statement about a trend across that boundary needs a constant floor.
    """
    from wildfires.config import MIN_FIRE_HA

    threshold = MIN_FIRE_HA if min_ha is None else min_ha
    return df[df[area_col] >= threshold].copy()


def check_landcover_sums(df: pd.DataFrame, tol: float = 1.0) -> pd.DataFrame:
    """Return the rows whose land-cover percentages do not sum to ~100.

    Expect roughly 1.6% of rows to fail (all-zero or all-null composition).
    A much larger share means the columns were mangled upstream.
    """
    from wildfires.io import EFFIS_LANDCOVER_COLS

    total = df[EFFIS_LANDCOVER_COLS].sum(axis=1, min_count=1)
    return df[~total.between(100 - tol, 100 + tol) | total.isna()]
