"""Tests for the join that the whole project rests on.

These run without the large data files: they exercise the transformation logic
on small fixtures. Derived-variable helpers moved to tests/test_features.py;
the full-data provenance checks are chapter 01.
"""

from __future__ import annotations

import pandas as pd
import pytest

from wildfires.clean import normalise_dtcc, normalise_name
from wildfires.config import PATHS


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


full_data = pytest.mark.skipif(
    not PATHS["raw"]["icnf_statistics"].exists()
    or not (PATHS["raw"]["ine_aer_dir"] / "AER2024_II_01.xlsx").exists(),
    reason="raw workbooks not present (run make fetch)",
)


@full_data
class TestPanels:
    @pytest.fixture(scope="class")
    def panel(self):
        from wildfires.merge import build_panel

        return build_panel()

    @pytest.fixture(scope="class")
    def fire_panel(self):
        from wildfires.merge import build_fire_panel

        return build_fire_panel()

    def test_panel_is_278_municipalities_by_six_years(self, panel):
        assert len(panel) == 1668
        assert panel.dtcc.nunique() == 278
        assert sorted(panel.year.unique()) == [2019, 2020, 2021, 2022, 2023, 2024]

    def test_panel_key_is_unique(self, panel):
        assert not panel.duplicated(["dtcc", "year"]).any()

    def test_join_lost_no_municipality(self, panel):
        """INE, ICNF and GADM overlap on exactly 278 mainland municipalities."""
        assert set(panel.groupby("year").size()) == {278}

    def test_demography_is_attached_everywhere(self, panel):
        for column in ("pop_total", "share_65_plus", "birth_rate", "pop_density"):
            assert panel[column].notna().sum() > 1500, f"{column} mostly unattached"

    def test_fire_columns_are_attached(self, panel):
        assert panel.n_fires.notna().all()

    def test_burn_rate_is_a_fraction(self, panel):
        rate = panel.burn_rate.dropna()
        assert (rate >= 0).all()
        assert (rate <= 1.5).all(), "burn_rate far above 1 means an area-unit mismatch"

    def test_fire_panel_spans_the_full_history(self, fire_panel):
        assert fire_panel.year.min() == 2001
        assert fire_panel.year.max() == 2025

    def test_fire_panel_carries_no_demography(self, fire_panel):
        """It must not inherit the 2019-2024 INE ceiling."""
        assert "pop_total" not in fire_panel.columns
        assert "birth_rate" not in fire_panel.columns

    def test_no_merge_multiplied_rows(self, fire_panel):
        assert not fire_panel.duplicated(["dtcc", "year"]).any()


@full_data
class TestMunicipalityAreas:
    def test_areas_are_plausible_for_portugal(self):
        from wildfires.merge import municipality_areas

        areas = municipality_areas()
        # Portugal's smallest concelho is São João da Madeira at ~8 km2; the
        # largest is Odemira at ~1720 km2.
        assert areas.municipality_area_km2.min() > 5
        assert areas.municipality_area_km2.max() < 2000
        assert len(areas) >= 278


@full_data
class TestTypologyTable:
    def test_is_nuts3_level_and_never_joined_to_municipalities(self):
        """II_01_04/_05 carry no municipality code; they stay a separate table."""
        from wildfires.merge import build_typology

        typology = build_typology()
        assert "dtcc" not in typology.columns
        assert set(typology.typology) == {"APU", "AMU", "APR"}

    def test_2022_gap_is_preserved(self):
        from wildfires.merge import build_typology

        assert 2022 not in set(build_typology().year)
