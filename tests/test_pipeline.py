"""Tests for the preprocessing stages.

Stages that need the 565 MB EFFIS files skip when those are absent; the INE and
ICNF workbooks are small enough to exercise directly.
"""

from __future__ import annotations

import pytest

from wildfires.config import PATHS

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
        """They answer different questions and must never be coalesced."""
        both = icnf[icnf.year >= 2017]
        assert not both.burned_ha_total.equals(both.burned_ha_total_ignited)

    def test_missing_marker_never_survives_as_a_string(self, icnf):
        numeric = icnf.drop(columns=["dtcc"])
        for column in numeric.columns:
            assert numeric[column].map(lambda v: isinstance(v, str)).sum() == 0
