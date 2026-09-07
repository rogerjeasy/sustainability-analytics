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

    def test_dtcc_is_four_characters(self, ine):
        assert ine.dtcc.str.len().eq(4).all()

    def test_rate_columns_are_populated(self, ine):
        # The real invariant, measured directly against the source workbooks:
        # all ten Task 1 indicator columns are fully populated for every one
        # of the 1,848 municipality-year rows. A weaker "> 1000" threshold
        # would silently absorb a partial merge failure (e.g. a code-column
        # shift in a future AER edition) instead of reporting it.
        for column in ("pop_density", "birth_rate", "death_rate",
                       "growth_effective", "growth_natural", "growth_migratory"):
            assert ine[column].notna().sum() == len(ine), f"{column} has missing values"

    def test_no_row_lost_its_indicator_block(self, ine):
        """Pins the merge completeness the reviewer verified by hand.

        `validate="one_to_one"` on the merge only rejects duplicate keys; it
        does not catch a partial key mismatch. If `indicators` stopped
        matching some rows, those rows would keep their population columns
        but carry NaN across every indicator column. Assert that never
        happens: zero rows with a fully-empty indicator block.
        """
        indicator_columns = [
            "pop_density", "growth_effective", "growth_natural", "growth_migratory",
            "birth_rate", "death_rate", "aging_index_ine", "renewal_index",
            "old_age_dependency_ine", "longevity_index",
        ]
        all_null = ine[indicator_columns].isna().all(axis=1)
        assert all_null.sum() == 0

    def test_derived_aging_index_matches_ine_published_value(self, ine):
        """Independent cross-check: our arithmetic against INE's own column."""
        both = ine[ine.aging_index.notna() & ine.aging_index_ine.notna()]
        assert len(both) == len(ine)
        assert (both.aging_index - both.aging_index_ine).abs().median() < 1.0

    def test_nothing_was_imputed(self, ine):
        """2021 density carries a break in series; values stay exactly as published."""
        assert ine[ine.year == 2021].pop_density.notna().sum() == 308


effis_only = pytest.mark.skipif(
    not PATHS["interim"]["effis_subset_geo"].exists(),
    reason="EFFIS geodata not present (run make fetch; ~565 MB)",
)


class TestEffisDuration:
    """Duration arithmetic, exercised on a fixture so it needs no 565 MB download."""

    def test_duration_is_days_between_first_and_final_date(self):
        import pandas as pd

        from wildfires.pipeline import add_fire_duration

        df = pd.DataFrame({
            "FIREDATE": pd.to_datetime(["2019-07-01T00:00:00", "2019-08-10T12:00:00"]),
            "FINALDATE": pd.to_datetime(["2019-07-04T00:00:00", "2019-08-11T00:00:00"]),
        })
        out = add_fire_duration(df)
        assert out.duration_days.tolist() == [3.0, 0.5]

    def test_missing_final_date_yields_na_not_zero(self):
        """An unclosed fire is unknown duration, not a zero-day fire."""
        import pandas as pd

        from wildfires.pipeline import add_fire_duration

        df = pd.DataFrame({
            "FIREDATE": pd.to_datetime(["2019-07-01"]),
            "FINALDATE": [pd.NaT],
        })
        assert add_fire_duration(df).duration_days.isna().all()


@effis_only
class TestEffisStage:
    @pytest.fixture(scope="class")
    def effis(self):
        from wildfires.pipeline import build_effis

        return build_effis()

    def test_one_row_per_municipality_year(self, effis):
        assert not effis.duplicated(["dtcc", "year"]).any()

    def test_dtcc_is_four_characters(self, effis):
        assert effis.dtcc.str.len().eq(4).all()

    def test_land_cover_means_are_percentages(self, effis):
        for column in [c for c in effis.columns if c.startswith("lc_")]:
            values = effis[column].dropna()
            assert values.between(0, 100).all(), f"{column} outside 0-100"

    def test_duration_is_never_negative(self, effis):
        assert (effis.effis_duration_days_max.dropna() >= 0).all()


effis_raw_only = pytest.mark.skipif(
    not PATHS["raw"]["effis_polygons"].exists(),
    reason="EFFIS shapefile not present (run make fetch; ~565 MB)",
)


@effis_raw_only
class TestEffisSubsetStage:
    """The subset must be reproducible from data/raw alone.

    Regression test for a fresh-clone failure: build_effis read an interim
    GeoPackage that no stage produced and `make fetch` did not download, so
    `make data` died on any machine where that file had not been created by hand.
    """

    @pytest.fixture(scope="class")
    @classmethod
    def subset(cls):
        from wildfires.pipeline import build_effis_subset

        return build_effis_subset()

    def test_keeps_only_the_four_study_countries(self, subset):
        assert set(subset.COUNTRY.dropna()) == {"ES", "FR", "IT", "PT"}

    def test_carries_geometry_in_epsg_4326(self, subset):
        assert subset.geometry.notna().any()
        assert subset.crs.to_string() == "EPSG:4326"

    def test_derives_fire_year_from_firedate(self, subset):
        years = subset.fire_year.dropna()
        assert years.min() >= 2000
        assert years.max() <= 2026

    def test_numeric_fields_are_numeric_not_text(self, subset):
        for column in ("AREA_HA", "PERCNA2K"):
            assert pd.api.types.is_numeric_dtype(subset[column]), column

    def test_is_a_strict_subset_of_the_raw_shapefile(self, subset):
        import geopandas as gpd

        raw = gpd.read_file(PATHS["raw"]["effis_polygons"])
        assert 0 < len(subset) < len(raw)
