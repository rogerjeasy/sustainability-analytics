"""Build the (municipality x year) analysis panel.

This is the riskiest step in the project: three sources at three different
granularities have to line up on one key. It lives here rather than in a
notebook so it can be tested (see tests/test_merge.py).

    EFFIS      freguesia-level polygons  -> spatial join to municipality
    ICNF       already municipality-year (DTCC)
    INE (AER)  municipality-year

Join key: ``dtcc``, the 4-digit Portuguese municipality code.
"""

from __future__ import annotations

import geopandas as gpd
import pandas as pd

from wildfires.config import CRS_METRIC, PATHS
from wildfires.io import (
    EFFIS_LANDCOVER_COLS,
    ICNF_CAUSE_COLS,
    load_effis_polygons,
    load_icnf,
    load_municipalities,
)


def effis_to_municipality(
    fires: gpd.GeoDataFrame | None = None,
    municipalities: gpd.GeoDataFrame | None = None,
) -> gpd.GeoDataFrame:
    """Assign each EFFIS burn polygon to a municipality by spatial join.

    EFFIS's ``COMMUNE`` field is the *freguesia* (civil parish), one level finer
    than the concelho, and is free text with no code — so it cannot be joined to
    ICNF or INE directly. The polygon centroid is used as the representative
    point; fires crossing a municipal border are attributed to a single
    municipality, which is a known and documented simplification.
    """
    fires = load_effis_polygons() if fires is None else fires
    municipalities = load_municipalities() if municipalities is None else municipalities

    # Centroids must be computed in a projected CRS to be geometrically valid.
    pts = fires.to_crs(CRS_METRIC).copy()
    pts["geometry"] = pts.geometry.representative_point()

    joined = gpd.sjoin(
        pts,
        municipalities.to_crs(CRS_METRIC)[["dtcc", "municipality", "district", "geometry"]],
        how="left",
        predicate="within",
    ).drop(columns="index_right")
    return joined


def aggregate_fires(fires_with_dtcc: pd.DataFrame) -> pd.DataFrame:
    """Collapse individual fire records to one row per (dtcc, year)."""
    df = fires_with_dtcc.copy()
    if "fire_year" not in df.columns:
        df["fire_year"] = pd.to_datetime(df["FIREDATE"], format="ISO8601").dt.year

    keys = ["dtcc", "fire_year"]
    grouped = df.groupby(keys)

    size = grouped["AREA_HA"].agg(
        n_fires="count",
        burnt_ha_total="sum",
        burnt_ha_median="median",
        burnt_ha_max="max",
    )

    # Mean land-cover composition of the area that burned in that municipality-year.
    composition = grouped[[*EFFIS_LANDCOVER_COLS, "PERCNA2K"]].mean()
    composition.columns = [f"{c.lower()}_mean" for c in composition.columns]

    out = size.join(composition).reset_index()
    return out.rename(columns={"fire_year": "year"})


def build_panel(save: bool = False) -> pd.DataFrame:
    """Assemble EFFIS + ICNF (+ INE) into the analysis panel.

    Returns one row per (dtcc, year). INE demography is left to notebook 01 to
    attach once the team fixes which AER indicators go in — see the TODO below.
    """
    fires = aggregate_fires(effis_to_municipality())

    icnf = load_icnf("concelho")
    icnf_cols = ["dtcc", "year", "Num_IncendiosRurais", "Ninc_Sup24h", *ICNF_CAUSE_COLS]
    icnf = icnf[[c for c in icnf_cols if c in icnf.columns]]

    panel = icnf.merge(fires, on=["dtcc", "year"], how="outer", validate="one_to_one")

    # TODO(Roger): attach INE demography from load_ine_population_all() once the
    # team agrees which AER indicators enter the panel. AER covers 2019-2024,
    # so this merge will restrict the usable study window.

    panel = panel.sort_values(["dtcc", "year"]).reset_index(drop=True)

    if save:
        out = PATHS["processed"]["panel"]
        out.parent.mkdir(parents=True, exist_ok=True)
        panel.to_parquet(out, index=False)
    return panel
