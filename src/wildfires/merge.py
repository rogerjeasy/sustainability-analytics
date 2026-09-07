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

import pandas as pd

from wildfires.config import PATHS
from wildfires.io import ICNF_CAUSE_COLS, load_icnf


def build_panel(save: bool = False) -> pd.DataFrame:
    """Assemble EFFIS + ICNF (+ INE) into the analysis panel.

    Returns one row per (dtcc, year). INE demography is left to notebook 01 to
    attach once the team fixes which AER indicators go in — see the TODO below.
    """
    # aggregate_fires/effis_to_municipality moved to pipeline.py in Task 9; this
    # function is rewritten in Task 10 to call the pipeline stages instead.
    fires = aggregate_fires(effis_to_municipality())  # noqa: F821

    icnf = load_icnf("concelho")
    icnf_cols = ["dtcc", "year", "Num_IncendiosRurais", "Ninc_Sup24h", *ICNF_CAUSE_COLS]
    icnf = icnf[[c for c in icnf_cols if c in icnf.columns]]

    panel = icnf.merge(fires, on=["dtcc", "year"], how="outer", validate="one_to_one")

    # TODO(Roger): attach INE demography from wildfires.ine.load_indicators_all()
    # once the team agrees which AER indicators enter the panel. AER covers
    # 2019-2024, so this merge will restrict the usable study window.

    panel = panel.sort_values(["dtcc", "year"]).reset_index(drop=True)

    if save:
        out = PATHS["processed"]["panel"]
        out.parent.mkdir(parents=True, exist_ok=True)
        panel.to_parquet(out, index=False)
    return panel
