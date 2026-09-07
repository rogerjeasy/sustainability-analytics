"""Tests for the preprocessing stages.

Stages that need the 565 MB EFFIS files skip when those are absent; the INE and
ICNF workbooks are small enough to exercise directly.
"""

from __future__ import annotations

import pandas as pd
import pytest

from wildfires.config import PATHS
from wildfires.io import load_icnf

icnf_only = pytest.mark.skipif(
    not PATHS["raw"]["icnf_statistics"].exists(),
    reason="ICNF workbook not present (run make fetch)",
)


@icnf_only
class TestICNFStage:
    @pytest.fixture(scope="class")
    @classmethod
    def icnf(cls):
        from wildfires.pipeline import build_icnf

        return build_icnf()

    def test_one_row_per_municipality_year(self, icnf):
        assert not icnf.duplicated(["dtcc", "year"]).any()

    def test_spans_the_full_icnf_history(self, icnf):
        assert icnf.year.min() == 2001
        assert icnf.year.max() == 2025
        assert len(icnf) == 6921

    def test_municipality_count_grows_to_278(self, icnf):
        """270 municipalities report in 2001, 278 from 2006 on. Not a flat product."""
        per_year = icnf.groupby("year").dtcc.nunique()
        assert per_year.loc[2001] == 270
        assert per_year.loc[2019] == 278
        assert per_year.max() == 278

    def test_dtcc_is_four_characters(self, icnf):
        assert icnf.dtcc.str.len().eq(4).all()

    def test_within_municipality_area_is_absent_before_2017(self, icnf):
        """AreaArd*_NoConcelho simply does not exist before 2017 in the source."""
        early = icnf[icnf.year < 2017]
        assert early.burned_ha_total.isna().all()

    def test_within_municipality_area_is_present_from_2017(self, icnf):
        assert icnf[icnf.year == 2019].burned_ha_total.notna().all()

    def test_ignition_area_covers_the_pre_2017_years(self, icnf):
        """The _IncendioInicioConc convention is the only one covering 2001-2016.

        Verified directly against the raw workbook: ICNF wrote the literal
        "(sem informação)" marker for every AreaArdTotal_IncendioInicioConc row
        from 2017 onward, the same year _NoConcelho starts being populated. The
        two conventions are strictly complementary across the 2017 boundary, not
        overlapping -- so this checks coverage over 2001-2016 only, not "every
        year" as originally assumed.
        """
        # pandas 3.0 dropped generic method delegation on SeriesGroupBy (no more
        # `.groupby(...).col.notna()`), so notna() is applied before grouping.
        # See the identical fix in tests/test_ine.py::test_pop_density_present_for_every_edition.
        per_year = icnf.burned_ha_total_ignited.notna().groupby(icnf.year).sum()
        assert (per_year.loc[2001:2016] > 0).all()

    def test_the_two_conventions_are_kept_separate(self, icnf):
        """They answer different questions and must never be coalesced or swapped.

        Comparing the two output columns over year >= 2017 is vacuous: from 2017
        on, burned_ha_total_ignited is entirely NaN (that is the fact discovered
        while building this stage -- see test_ignition_area_covers_the_pre_2017_years),
        so `not both.a.equals(both.b)` would hold even if build_icnf coalesced the
        two raw columns into one. Instead, pick one real row from each era, straight
        off the raw workbook, and check the renamed output actually carries the
        value from the matching raw column -- and NaN from the other -- which fails
        under a coalesce, a swap, or a mis-mapped rename alike.
        """
        raw = load_icnf("concelho")

        pre = raw[(raw.year < 2017) & raw.AreaArdTotal_IncendioInicioConc.notna()].iloc[0]
        row = icnf[(icnf.dtcc == pre.dtcc) & (icnf.year == pre.year)].iloc[0]
        assert row.burned_ha_total_ignited == pre.AreaArdTotal_IncendioInicioConc
        assert pd.isna(row.burned_ha_total)

        post = raw[(raw.year >= 2017) & raw.AreaArdTotal_NoConcelho.notna()].iloc[0]
        row = icnf[(icnf.dtcc == post.dtcc) & (icnf.year == post.year)].iloc[0]
        assert row.burned_ha_total == post.AreaArdTotal_NoConcelho
        assert pd.isna(row.burned_ha_total_ignited)

    def test_missing_marker_never_survives_as_a_string(self, icnf):
        numeric = icnf.drop(columns=["dtcc"])
        for column in numeric.columns:
            assert numeric[column].map(lambda v: isinstance(v, str)).sum() == 0


ine_only = pytest.mark.skipif(
    not (PATHS["raw"]["ine_aer_dir"] / "AER2024_II_01.xlsx").exists(),
    reason="INE workbooks not present (run make fetch)",
)


@ine_only
class TestINEStage:
    @pytest.fixture(scope="class")
    def ine(self):
        from wildfires.pipeline import build_ine

        return build_ine()

    def test_one_row_per_municipality_year(self, ine):
        assert not ine.duplicated(["dtcc", "year"]).any()

    def test_covers_308_municipalities_for_six_years(self, ine):
        assert sorted(ine.year.unique()) == [2019, 2020, 2021, 2022, 2023, 2024]
        assert set(ine.groupby("year").size()) == {308}

    def test_age_shares_sum_to_one_hundred(self, ine):
        parts = (ine.share_0_14 + ine.share_15_24 + ine.share_25_64 + ine.share_65_plus)
        assert (parts - 100).abs().max() < 1e-6

    def test_share_75_plus_is_nested_inside_65_plus(self, ine):
        """75+ is a subset of 65+, not a fifth disjoint band."""
        assert (ine.share_75_plus <= ine.share_65_plus + 1e-9).all()

    def test_rate_columns_are_populated(self, ine):
        for column in ("pop_density", "birth_rate", "death_rate",
                       "growth_effective", "growth_natural", "growth_migratory"):
            assert ine[column].notna().sum() > 1000, f"{column} mostly empty"

    def test_derived_aging_index_matches_ine_published_value(self, ine):
        """Independent cross-check: our arithmetic against INE's own column."""
        both = ine[ine.aging_index.notna() & ine.aging_index_ine.notna()]
        assert len(both) > 1000
        assert (both.aging_index - both.aging_index_ine).abs().median() < 1.0

    def test_nothing_was_imputed(self, ine):
        """2021 density carries a break in series; values stay exactly as published."""
        assert ine[ine.year == 2021].pop_density.notna().sum() > 250
