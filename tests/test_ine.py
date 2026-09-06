"""Tests for the INE AER population parser.

These need the real workbooks, which are gitignored, so they skip when the data
is not present rather than fail on a fresh clone.
"""

from __future__ import annotations

import pytest

from wildfires.config import PATHS
from wildfires.ine import (
    SHEET_SPEC,
    TYPOLOGY_SHEET,
    add_aging_measures,
    add_territory_level,
    load_indicators_all,
    load_indicators_year,
    load_population_all,
    load_typology_all,
    normalise_indicator,
    series_breaks,
)

pytestmark = pytest.mark.skipif(
    not (PATHS["raw"]["ine_aer_dir"] / "AER2024_II_01.xlsx").exists(),
    reason="INE AER workbooks not present (see data/README.md)",
)


@pytest.fixture(scope="module")
def population():
    return add_territory_level(load_population_all())


class TestPopulationParse:
    def test_covers_every_edition(self, population):
        assert sorted(population.year.unique()) == sorted(SHEET_SPEC)

    def test_age_groups_sum_to_printed_total(self, population):
        """The strongest check available: the parse must reproduce INE's own Total.

        A column misalignment between the main and continuation sheets would
        break this immediately.
        """
        parts = (population.pop_0_14 + population.pop_15_24
                 + population.pop_25_64 + population.pop_65_plus)
        diff = (population.pop_total - parts).abs()
        assert diff.max() == 0

    def test_all_308_municipalities_every_year(self, population):
        counts = population[population.level == "municipality"].groupby("year").size()
        assert set(counts) == {308}

    def test_elderly_counts_are_present_for_split_editions(self, population):
        """65+ lives in the 'c' continuation sheet for 2019-2022.

        Reading only the main sheet would leave these null and silently zero out
        every aging measure for those years.
        """
        for year in (2019, 2020, 2021, 2022):
            rows = population[population.year == year]
            assert rows.pop_65_plus.notna().all()
            assert (rows.pop_65_plus > 0).all()


class TestTypology:
    def test_2022_is_absent_not_interpolated(self):
        """AER2022 does not publish table II.1.5 — that gap must stay a gap."""
        assert 2022 not in TYPOLOGY_SHEET
        assert 2022 not in set(load_typology_all().year)

    def test_rural_population_falls_while_urban_rises(self):
        """The finding the presentation rests on, pinned against the source."""
        t = load_typology_all()
        pt = t[t.territory.str.lower() == "portugal"]
        first, last = pt.year.min(), pt.year.max()

        def total(year, typ):
            return pt[(pt.year == year) & (pt.typology == typ)].pop_total.item()

        assert total(last, "APR") < total(first, "APR")
        assert total(last, "APU") > total(first, "APU")


class TestAgingMeasures:
    def test_aging_index_is_elderly_per_hundred_children(self, population):
        df = add_aging_measures(population)
        row = df[(df.year == 2024) & (df.level == "country")].iloc[0]
        assert row.aging_index == pytest.approx(
            100 * row.pop_65_plus / row.pop_0_14
        )


class TestNormaliseIndicator:
    def test_strips_break_in_series_marker(self):
        # AER2021 writes 'Densidade populacional \n┴'. The trailing sign is why
        # an exact-string match silently drops pop_density for 2021 alone.
        assert normalise_indicator("Densidade populacional \n┴") == "Densidade populacional"

    def test_strips_other_conventional_signs(self):
        assert normalise_indicator("Taxa bruta de natalidade §") == "Taxa bruta de natalidade"

    def test_collapses_internal_whitespace(self):
        assert normalise_indicator("Índice  de\nlongevidade") == "Índice de longevidade"


class TestIndicators:
    def test_pop_density_present_for_every_edition(self):
        """Regression: the 2021 break-in-series marker must not drop the column."""
        df = load_indicators_all()
        muni = df[df.code.str.len().eq(7) & df.code.str[3:].ne("0000")]
        # pandas 3.0 dropped generic method delegation on SeriesGroupBy (no more
        # `.groupby(...).col.notna()`), so notna() is applied before grouping.
        counts = muni.pop_density.notna().groupby(muni.year).sum()
        assert (counts > 0).all(), f"pop_density missing for {counts[counts == 0].index.tolist()}"

    def test_all_six_rate_columns_populated_every_year(self):
        df = load_indicators_all()
        for col in ("pop_density", "growth_effective", "growth_natural",
                    "growth_migratory", "birth_rate", "death_rate"):
            per_year = df[col].notna().groupby(df.year).sum()
            assert (per_year > 0).all(), f"{col} empty in {per_year[per_year == 0].index.tolist()}"

    def test_dependency_index_uses_the_real_ine_label(self):
        """INE writes 'de idosas/os', not 'de idosos'. Wrong label = silent all-null."""
        df = load_indicators_year(2024)
        assert df.old_age_dependency_ine.notna().any()

    def test_continuation_columns_survive_position_shift(self):
        """II_01_01c shifts columns between editions; name lookup must absorb it."""
        for year in (2019, 2022, 2024):
            df = load_indicators_year(year)
            assert df.aging_index_ine.notna().any(), f"aging index lost in {year}"
            assert df.longevity_index.notna().any(), f"longevity lost in {year}"

    def test_308_municipalities_every_year(self):
        df = load_indicators_all()
        muni = df[df.code.str.len().eq(7) & df.code.str[3:].ne("0000")]
        assert set(muni.groupby("year").size()) == {308}

    def test_missing_markers_become_nan_not_strings(self):
        df = load_indicators_all()
        assert df.pop_density.map(lambda v: isinstance(v, str)).sum() == 0


class TestSeriesBreaks:
    def test_records_the_2021_density_break(self):
        breaks = series_breaks()
        row = breaks[(breaks.year == 2021) & (breaks.sheet == "II_01_01")]
        assert "Densidade populacional" in set(row.indicator)

    def test_records_the_2022_life_expectancy_breaks(self):
        breaks = series_breaks()
        got = set(breaks[(breaks.year == 2022) & (breaks.sheet == "II_01_01c")].indicator)
        assert "Esperança de vida à nascença" in got
        assert "Esperança de vida aos 65 anos" in got

    def test_breaks_do_not_alter_values(self):
        """The flag is metadata. 2021 density must still carry real numbers."""
        df = load_indicators_year(2021)
        assert df.pop_density.notna().sum() > 300


class TestSingleINEReader:
    def test_io_exposes_no_ine_loaders(self):
        """One reader, not two. Duplicated parsers drift and disagree silently."""
        import wildfires.io as io_module

        leaked = [n for n in dir(io_module) if "ine_population" in n]
        assert leaked == [], f"io.py still exports INE loaders: {leaked}"

    def test_io_drops_the_nonexistent_dimensions_loader(self):
        """raw/dimensions/superficies-por-concelho-2022.csv is not on disk.

        Municipality area comes from GADM geometry in EPSG:3763 instead.
        """
        import wildfires.io as io_module

        assert not hasattr(io_module, "load_municipality_dimensions")

    def test_paths_no_longer_declares_municipality_dimensions(self):
        from wildfires.config import PATHS

        assert "municipality_dimensions" not in PATHS["raw"]
