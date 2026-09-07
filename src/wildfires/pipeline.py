"""The preprocessing stages that turn data/raw into analysis-ready datasets.

Each stage writes exactly one artifact and can be run on its own, so a failure
part-way through does not discard the work already done.
"""

from __future__ import annotations

import geopandas as gpd
import pandas as pd

from wildfires.config import CRS_METRIC, PATHS
from wildfires.ine import (
    add_aging_measures,
    add_territory_level,
    load_indicators_all,
    load_population_all,
    series_breaks,
)
from wildfires.io import EFFIS_LANDCOVER_COLS, load_effis_polygons, load_icnf, load_municipalities

# ICNF publishes two burned-area conventions that answer different questions:
#
#   _NoConcelho          area that burned WITHIN this municipality
#   _IncendioInicioConc  area of fires that IGNITED in this municipality
#
# _NoConcelho is empty before 2017. Both are carried, distinctly named; coalescing
# them would silently mix two different measures across the 2017 boundary.
ICNF_AREA_WITHIN = {
    "AreaArdTotal_NoConcelho": "burned_ha_total",
    "AreaArdPov_NoConcelho": "burned_ha_forest",
    "AreaArdMato_NoConcelho": "burned_ha_shrub",
    "AreaArdAgric_NoConcelho": "burned_ha_agric",
}
ICNF_AREA_IGNITED = {
    "AreaArdTotal_IncendioInicioConc": "burned_ha_total_ignited",
    "AreaArdPov_IncendioInicioConc": "burned_ha_forest_ignited",
    "AreaArdMato_IncendioInicioConc": "burned_ha_shrub_ignited",
    "AreaArdAgric_IncendioInicioConc": "burned_ha_agric_ignited",
}
ICNF_SIZE_CLASSES = {
    "NIncRur_0_1ha": "n_fires_0_1ha",
    "NIncRur_1_10ha": "n_fires_1_10ha",
    "NIncRur_10_20ha": "n_fires_10_20ha",
    "NIncRur_20_50ha": "n_fires_20_50ha",
    "NIncRur_50_100ha": "n_fires_50_100ha",
    "NIncRur_100_500ha": "n_fires_100_500ha",
    "NIncRur_500_1000ha": "n_fires_500_1000ha",
    "NIncRur_1000_n_ha": "n_fires_1000_plus_ha",
}
ICNF_CAUSES = {
    "NInc_Natural": "cause_natural",
    "NInc_Negligente": "cause_negligent",
    "NInc_Intencionais": "cause_intentional",
    "NInc_Reacendimentos": "cause_rekindle",
    "NInc_Desconhecida": "cause_unknown",
    "NInc_NaoInvestigados": "cause_uninvestigated",
}
ICNF_RENAMES = {
    "Num_IncendiosRurais": "n_fires",
    "Ninc_Sup24h": "n_fires_gt24h",
    **ICNF_AREA_WITHIN, **ICNF_AREA_IGNITED, **ICNF_SIZE_CLASSES, **ICNF_CAUSES,
}


def build_icnf(save: bool = False) -> pd.DataFrame:
    """ICNF rural fire statistics as one tidy row per (dtcc, year), 2001-2025."""
    df = load_icnf("concelho")
    df = df.rename(columns=ICNF_RENAMES)

    keep = ["dtcc", "year", *[c for c in ICNF_RENAMES.values() if c in df.columns]]
    out = df[keep].copy()

    for column in out.columns.drop(["dtcc", "year"]):
        out[column] = pd.to_numeric(out[column], errors="coerce")

    out = out.sort_values(["dtcc", "year"]).reset_index(drop=True)
    if save:
        target = PATHS["interim"]["icnf_municipal_year"]
        target.parent.mkdir(parents=True, exist_ok=True)
        out.to_parquet(target, index=False)
    return out


def build_ine(save: bool = False) -> pd.DataFrame:
    """INE demography as one row per (dtcc, year) for the six AER editions.

    Age-group counts come from the II_01_03/_02 tables, the rates and density from
    II_01_01/_01c. Both are keyed on the 7-digit hierarchical code, whose last four
    characters are the dtcc.
    """
    population = add_aging_measures(add_territory_level(load_population_all()))
    population = population[population.level == "municipality"].copy()

    # add_aging_measures already computed share_0_14 and share_65_plus; only the
    # remaining three bands are genuinely missing. Recomputing the first two here
    # too would create a second definition that has to be kept in sync with the
    # one in wildfires.ine, for no benefit.
    for band in ("15_24", "25_64", "75_plus"):
        population[f"share_{band}"] = 100 * population[f"pop_{band}"] / population["pop_total"]

    indicators = load_indicators_all()
    indicators = indicators[
        indicators.code.str.len().eq(7) & indicators.code.str[3:].ne("0000")
    ].copy()

    merged = population.merge(
        indicators.drop(columns=["territory"]),
        on=["code", "year"], how="left", validate="one_to_one",
    )
    merged["dtcc"] = merged["code"].str[-4:]

    columns = [
        "dtcc", "year", "territory",
        "pop_total", "pop_0_14", "pop_15_24", "pop_25_64", "pop_65_plus", "pop_75_plus",
        "share_0_14", "share_15_24", "share_25_64", "share_65_plus", "share_75_plus",
        "aging_index", "old_age_dependency",
        "pop_density", "growth_effective", "growth_natural", "growth_migratory",
        "birth_rate", "death_rate",
        "aging_index_ine", "renewal_index", "old_age_dependency_ine", "longevity_index",
    ]
    out = merged[columns].sort_values(["dtcc", "year"]).reset_index(drop=True)

    if save:
        target = PATHS["interim"]["ine_municipal_year"]
        target.parent.mkdir(parents=True, exist_ok=True)
        out.to_parquet(target, index=False)

        breaks = PATHS["processed"]["series_breaks"]
        breaks.parent.mkdir(parents=True, exist_ok=True)
        series_breaks().to_csv(breaks, index=False)
    return out


def effis_to_municipality(
    fires: gpd.GeoDataFrame | None = None,
    municipalities: gpd.GeoDataFrame | None = None,
) -> gpd.GeoDataFrame:
    """Assign each EFFIS burn polygon to a municipality by spatial join.

    EFFIS's COMMUNE field is the freguesia (civil parish), one level finer than the
    concelho, and is free text with no code, so it cannot be joined to ICNF or INE
    directly. The polygon representative point is used; a fire crossing a municipal
    border is attributed to one municipality, a known and documented simplification.
    """
    fires = load_effis_polygons() if fires is None else fires
    municipalities = load_municipalities() if municipalities is None else municipalities

    # Representative points must be computed in a projected CRS to be valid.
    pts = fires.to_crs(CRS_METRIC).copy()
    pts["geometry"] = pts.geometry.representative_point()

    joined = gpd.sjoin(
        pts,
        municipalities.to_crs(CRS_METRIC)[["dtcc", "municipality", "district", "geometry"]],
        how="left",
        predicate="within",
    ).drop(columns="index_right")
    return joined


def add_fire_duration(df: pd.DataFrame) -> pd.DataFrame:
    """Days between FIREDATE and FINALDATE.

    A fire with no FINALDATE has unknown duration, which stays NaN. Filling it
    with zero would report the longest-burning fires as the shortest.
    """
    out = df.copy()
    out["duration_days"] = (
        pd.to_datetime(out["FINALDATE"], errors="coerce")
        - pd.to_datetime(out["FIREDATE"], errors="coerce")
    ).dt.total_seconds() / 86400
    return out


def build_effis(save: bool = False) -> pd.DataFrame:
    """EFFIS burn perimeters aggregated to one row per (dtcc, year)."""
    fires = add_fire_duration(effis_to_municipality())
    fires = fires[fires["dtcc"].notna()].copy()
    if "fire_year" not in fires.columns:
        fires["fire_year"] = pd.to_datetime(
            fires["FIREDATE"], format="ISO8601", errors="coerce"
        ).dt.year

    grouped = fires.groupby(["dtcc", "fire_year"])
    size = grouped["AREA_HA"].agg(
        effis_n_fires="count",
        effis_burnt_ha_total="sum",
        effis_burnt_ha_median="median",
        effis_burnt_ha_max="max",
    )
    duration = grouped["duration_days"].agg(
        effis_duration_days_mean="mean",
        effis_duration_days_max="max",
    )
    composition = grouped[[*EFFIS_LANDCOVER_COLS, "PERCNA2K"]].mean()
    composition.columns = [f"lc_{c.lower()}_mean" for c in EFFIS_LANDCOVER_COLS] + \
                          ["percna2k_mean"]

    out = (
        size.join(duration).join(composition)
        .reset_index().rename(columns={"fire_year": "year"})
    )
    out["year"] = out["year"].astype("Int64")
    out = out.sort_values(["dtcc", "year"]).reset_index(drop=True)

    if save:
        target = PATHS["interim"]["effis_municipal_year"]
        target.parent.mkdir(parents=True, exist_ok=True)
        out.to_parquet(target, index=False)
    return out
