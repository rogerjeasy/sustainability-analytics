"""Tests for the panel contract checks. These run on fixtures, never on real data."""

from __future__ import annotations

import pandas as pd

from wildfires.validate import (
    Check,
    null_rate_table,
    render_null_rates,
    render_report,
    validate_fire_panel,
    validate_panel,
)


def _panel(rows=1668, municipalities=278):
    years = [2019, 2020, 2021, 2022, 2023, 2024]
    dtccs = [f"{i:04d}" for i in range(1, municipalities + 1)]
    frame = pd.DataFrame(
        [(d, y) for d in dtccs for y in years], columns=["dtcc", "year"]
    ).head(rows)
    frame["n_fires"] = 1.0
    frame["pop_total"] = 1000.0
    return frame


def _fire_panel():
    """6,921 rows is the real shape: 270 municipalities in 2001 rising to 278 by 2006."""
    years = list(range(2001, 2026))
    dtccs = [f"{i:04d}" for i in range(1, 279)]
    frame = pd.DataFrame([(d, y) for d in dtccs for y in years], columns=["dtcc", "year"])
    frame["n_fires"] = 1.0
    # The pre-2017 convention populates only its own era, and vice versa.
    frame["burned_ha_total"] = frame.year.where(frame.year >= 2017).notna().replace(
        {False: pd.NA, True: 1.0}
    )
    frame["burned_ha_total_ignited"] = frame.year.where(frame.year <= 2016).notna().replace(
        {False: pd.NA, True: 1.0}
    )
    return frame


class TestValidatePanel:
    def test_clean_panel_passes_everything(self):
        assert all(c.passed for c in validate_panel(_panel()))

    def test_duplicate_key_is_caught(self):
        frame = pd.concat([_panel(), _panel().head(1)], ignore_index=True)
        failures = [c for c in validate_panel(frame) if not c.passed]
        assert any("unique" in c.name for c in failures)

    def test_wrong_row_count_is_caught(self):
        failures = [c for c in validate_panel(_panel(rows=1000)) if not c.passed]
        assert any("row count" in c.name for c in failures)

    def test_missing_municipality_is_caught(self):
        failures = [c for c in validate_panel(_panel(municipalities=277)) if not c.passed]
        assert any("municipalities" in c.name for c in failures)

    def test_wrong_year_span_is_caught(self):
        frame = _panel()
        frame.loc[frame.year == 2024, "year"] = 2025
        failures = [c for c in validate_panel(frame) if not c.passed]
        assert any("years" in c.name for c in failures)

    def test_all_null_column_is_caught(self):
        """An entirely empty column means a rename or join silently failed."""
        frame = _panel()
        frame["birth_rate"] = pd.NA
        failures = [c for c in validate_panel(frame) if not c.passed]
        assert any("all-null" in c.name for c in failures)

    def test_empty_ignited_columns_are_expected_not_failures(self):
        """ICNF's pre-2017 convention contributes no rows to 2019-2024.

        Every ``*_ignited`` column is therefore 100% null in a *correct* analysis
        panel. Flagging that would make the build refuse a good panel.
        """
        frame = _panel()
        for column in (
            "burned_ha_total_ignited",
            "burned_ha_forest_ignited",
            "burned_ha_shrub_ignited",
            "burned_ha_agric_ignited",
            "burn_rate_ignited",
        ):
            frame[column] = pd.NA
        assert all(c.passed for c in validate_panel(frame))


class TestValidateFirePanel:
    def test_clean_fire_panel_passes_everything(self):
        assert all(c.passed for c in validate_fire_panel(_fire_panel()))

    def test_truncated_history_is_caught(self):
        frame = _fire_panel()
        frame = frame[frame.year >= 2005]
        failures = [c for c in validate_fire_panel(frame) if not c.passed]
        assert any("2001" in c.name for c in failures)

    def test_leaked_demography_is_caught(self):
        frame = _fire_panel()
        frame["pop_total"] = 1000.0
        failures = [c for c in validate_fire_panel(frame) if not c.passed]
        assert any("demography" in c.name for c in failures)

    def test_empty_burned_area_column_is_caught(self):
        """Both conventions are populated in their own era across 2001-2025.

        An all-null ``burned_ha_total`` here is a genuine regression, not an
        expected gap, so nothing in the fire panel is exempt from the check.
        """
        frame = _fire_panel()
        frame["burned_ha_total"] = pd.NA
        failures = [c for c in validate_fire_panel(frame) if not c.passed]
        assert any("all-null" in c.name for c in failures)

    def test_duplicate_key_is_caught(self):
        frame = pd.concat([_fire_panel(), _fire_panel().head(1)], ignore_index=True)
        failures = [c for c in validate_fire_panel(frame) if not c.passed]
        assert any("unique" in c.name for c in failures)


class TestRenderReport:
    def test_report_names_the_failing_check(self):
        results = {"panel": [Check(name="row count", passed=False, detail="got 3")]}
        text = render_report(results)
        assert "row count" in text
        assert "got 3" in text
        assert "FAIL" in text

    def test_report_marks_a_clean_run(self):
        results = {"panel": [Check(name="row count", passed=True, detail="1668")]}
        assert "PASS" in render_report(results)

    def test_report_explains_the_expected_gaps(self):
        text = render_report({"panel": [Check(name="row count", passed=True, detail="1668")]})
        assert "burn_rate_ignited" in text


class TestNullRates:
    def test_table_is_sorted_worst_first(self):
        frame = _panel()
        frame["mostly_missing"] = pd.NA
        table = null_rate_table(frame)
        assert table.iloc[0].column == "mostly_missing"
        assert table.iloc[0].null_pct == 100.0

    def test_rendered_table_is_markdown_with_every_column(self):
        frame = _panel()
        text = render_null_rates(frame)
        assert text.startswith("| Column | Null % |")
        for column in frame.columns:
            assert f"`{column}`" in text
