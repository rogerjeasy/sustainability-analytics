"""The preprocessing stages that turn data/raw into analysis-ready datasets.

Each stage writes exactly one artifact and can be run on its own, so a failure
part-way through does not discard the work already done.
"""

from __future__ import annotations

import pandas as pd

from wildfires.config import PATHS
from wildfires.io import load_icnf

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
