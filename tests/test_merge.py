"""Tests for the join that the whole project rests on.

These run without the large data files: they exercise the transformation logic
on small fixtures. The full-data sanity checks live in notebook 01.
"""

from __future__ import annotations

import pandas as pd
import pytest

from wildfires.clean import normalise_dtcc, normalise_name
from wildfires.features import add_lags, cause_shares


class TestNormaliseDtcc:
    def test_zero_pads_to_four_characters(self):
        # ICNF writes 101; GADM writes "0101". They must meet in the middle.
        out = normalise_dtcc(pd.Series([101, 1105, 1612]))
        assert out.tolist() == ["0101", "1105", "1612"]

    def test_missing_values_survive_as_na(self):
        out = normalise_dtcc(pd.Series([101, None]))
        assert out.isna().sum() == 1


class TestNormaliseName:
    def test_strips_accents_and_case(self):
        assert normalise_name(pd.Series(["Águeda"]))[0] == "agueda"

    def test_collapses_internal_whitespace(self):
        assert normalise_name(pd.Series(["Castelo  de   Paiva"]))[0] == "castelo de paiva"


class TestAddLags:
    def test_lag_does_not_leak_across_municipalities(self):
        df = pd.DataFrame({
            "dtcc": ["0101", "0101", "0102", "0102"],
            "year": [2019, 2020, 2019, 2020],
            "burnt_ha_total": [10.0, 20.0, 30.0, 40.0],
        })
        out = add_lags(df, ["burnt_ha_total"], lags=1)

        # First year of each municipality has no predecessor.
        first_rows = out[out["year"] == 2019]
        assert first_rows["burnt_ha_total_lag1"].isna().all()

        # 0102's 2020 lag must be 30 (its own 2019), not 20 (0101's last year).
        val = out.loc[(out["dtcc"] == "0102") & (out["year"] == 2020), "burnt_ha_total_lag1"]
        assert val.item() == 30.0


class TestCauseShares:
    def test_shares_sum_to_one(self):
        df = pd.DataFrame({
            "NInc_Natural": [1.0], "NInc_Negligente": [2.0], "NInc_Intencionais": [1.0],
            "NInc_Reacendimentos": [0.0], "NInc_Desconhecida": [0.0],
            "NInc_NaoInvestigados": [0.0],
        })
        assert cause_shares(df).sum(axis=1).item() == pytest.approx(1.0)

    def test_zero_total_gives_na_not_division_error(self):
        df = pd.DataFrame({
            "NInc_Natural": [0.0], "NInc_Negligente": [0.0], "NInc_Intencionais": [0.0],
            "NInc_Reacendimentos": [0.0], "NInc_Desconhecida": [0.0],
            "NInc_NaoInvestigados": [0.0],
        })
        assert cause_shares(df).isna().all(axis=None)
