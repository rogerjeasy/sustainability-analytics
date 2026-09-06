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
    load_population_all,
    load_typology_all,
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
