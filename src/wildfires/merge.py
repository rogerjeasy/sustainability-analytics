"""Build the (municipality x year) analysis panel.

This is the riskiest step in the project: three sources at three different
granularities have to line up on one key. It lives here rather than in a
notebook so it can be tested (see tests/test_merge.py).

    EFFIS      freguesia-level polygons  -> spatial join to municipality (pipeline.py)
    ICNF       already municipality-year (DTCC)
    INE (AER)  municipality-year

Join key: ``dtcc``, the 4-digit Portuguese municipality code.

Imports flow one way: this module calls into ``pipeline.py``, never the reverse.
"""

from __future__ import annotations

import pandas as pd

from wildfires.config import CRS_METRIC, PATHS
from wildfires.ine import load_typology_all
from wildfires.io import load_municipalities
from wildfires.pipeline import build_effis, build_icnf, build_ine


def municipality_areas() -> pd.DataFrame:
    """Municipality area in km2, computed from GADM geometry in a metric CRS.

    Replaces the data.gov.pt dimensions table, which is not distributed with this
    project. EPSG:3763 (PT-TM06/ETRS89) is the projection areas must be measured in;
    computing area in EPSG:4326 would return square degrees.
    """
    gdf = load_municipalities(mainland_only=True).to_crs(CRS_METRIC)
    return pd.DataFrame({
        "dtcc": gdf["dtcc"].astype("string"),
        "municipality_area_km2": gdf.geometry.area / 1e6,
    }).dropna(subset=["dtcc"]).reset_index(drop=True)


def build_fire_panel(save: bool = False) -> pd.DataFrame:
    """ICNF + EFFIS, 2001-2025. Carries no demography, so no 2019-2024 ceiling.

    ICNF changed its burned-area convention at 2017 with no overlap year:
    ``burned_ha_total`` (and its _forest/_shrub/_agric siblings) is populated
    2017-2025 only, while ``burned_ha_total_ignited`` (and its siblings) is
    populated 2001-2016 only. Neither can be backfilled from the other, so
    ``burn_rate`` and ``burn_rate_ignited`` are each NaN for the era the other
    convention covers — that is expected, not a bug, and downstream consumers
    must not assume both are populated in the same row.
    """
    icnf = build_icnf()
    effis = build_effis()

    panel = icnf.merge(effis, on=["dtcc", "year"], how="left", validate="one_to_one")
    panel = panel.merge(municipality_areas(), on="dtcc", how="left", validate="many_to_one")

    hectares = panel["municipality_area_km2"] * 100
    panel["burn_rate"] = panel["burned_ha_total"] / hectares
    panel["burn_rate_ignited"] = panel["burned_ha_total_ignited"] / hectares

    panel = panel.sort_values(["dtcc", "year"]).reset_index(drop=True)
    if save:
        target = PATHS["processed"]["fire_panel"]
        target.parent.mkdir(parents=True, exist_ok=True)
        panel.to_parquet(target, index=False)
    return panel


def build_panel(save: bool = False) -> pd.DataFrame:
    """The analysis panel: fire + demography, one row per (dtcc, year), 2019-2024.

    The inner join on INE is deliberate. INE AER exists only for 2019-2024 and
    covers 308 municipalities; ICNF covers 278 mainland ones. The 278 that appear
    in both are the analysis population, and every one of them matches.

    Within this window, ICNF's burned-area convention is ``_NoConcelho`` only
    (burned_ha_total and its siblings); the pre-2017 ``_ignited`` convention
    contributes no rows here, so ``burn_rate_ignited`` and every ``*_ignited``
    column are 100% NaN across the whole panel. They are kept rather than
    dropped: they are a documented, explicitly-empty part of the schema, not
    missing data to be silently discarded.
    """
    fire = build_fire_panel()
    demography = build_ine()

    panel = fire.merge(demography, on=["dtcc", "year"], how="inner", validate="one_to_one")
    panel = panel.sort_values(["dtcc", "year"]).reset_index(drop=True)

    if save:
        target = PATHS["processed"]["panel"]
        target.parent.mkdir(parents=True, exist_ok=True)
        panel.to_parquet(target, index=False)
    return panel


def build_typology(save: bool = False) -> pd.DataFrame:
    """INE tables II.1.4/II.1.5: population by urban typology, at NUTS III.

    Kept deliberately separate: these tables carry no municipality code, so they
    cannot join to the panel. AER2022 does not publish them, and that gap stays a
    gap rather than being filled from a neighbouring year.
    """
    typology = load_typology_all()
    if save:
        target = PATHS["processed"]["typology_nuts3"]
        target.parent.mkdir(parents=True, exist_ok=True)
        typology.to_parquet(target, index=False)
    return typology
