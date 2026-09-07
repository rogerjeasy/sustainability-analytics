"""Tests for the derived variables the analysis chapters share.

These fixtures use the column names the *built panel* actually has. The previous
versions of these tests used the pre-pipeline names (``burnt_ha_total``,
``NInc_*``), so they passed while the functions raised KeyError — or, worse,
returned an empty frame — on every real panel they were given.
"""

from __future__ import annotations

import pandas as pd
import pytest

from wildfires.features import add_lags, cause_shares, fire_occurred, log1p_safe

CAUSE_COLUMNS = [
    "cause_natural", "cause_negligent", "cause_intentional",
    "cause_rekindle", "cause_unknown", "cause_uninvestigated",
]


def _panel_like(**overrides):
    """A minimal frame shaped like data/processed/panel_municipality_year.parquet."""
    frame = pd.DataFrame({
        "dtcc": ["0101", "0101", "0102", "0102"],
        "year": [2019, 2020, 2019, 2020],
        "burned_ha_total": [0.0, 20.0, 30.0, 40.0],
        "burned_ha_total_ignited": [None, None, None, None],
    })
    for column, values in overrides.items():
        frame[column] = values
    return frame


class TestAddLags:
    def test_lag_does_not_leak_across_municipalities(self):
        out = add_lags(_panel_like(), ["burned_ha_total"], lags=1)

        # First year of each municipality has no predecessor.
        assert out.loc[out.year == 2019, "burned_ha_total_lag1"].isna().all()

        # 0102's 2020 lag must be 30 (its own 2019), not 20 (0101's last year).
        val = out.loc[(out.dtcc == "0102") & (out.year == 2020), "burned_ha_total_lag1"]
        assert val.item() == 30.0


class TestLog1pSafe:
    def test_zeros_survive_as_zero(self):
        assert log1p_safe(pd.Series([0.0])).item() == 0.0

    def test_negatives_are_clipped_not_nan(self):
        assert log1p_safe(pd.Series([-5.0])).item() == 0.0


class TestCauseShares:
    def test_shares_sum_to_one(self):
        frame = pd.DataFrame([[1.0, 2.0, 1.0, 0.0, 0.0, 0.0]], columns=CAUSE_COLUMNS)
        assert cause_shares(frame).sum(axis=1).item() == pytest.approx(1.0)

    def test_zero_total_gives_na_not_division_error(self):
        frame = pd.DataFrame([[0.0] * 6], columns=CAUSE_COLUMNS)
        assert cause_shares(frame).isna().all(axis=None)

    def test_output_columns_are_named_for_the_panel(self):
        frame = pd.DataFrame([[1.0, 1.0, 0.0, 0.0, 0.0, 0.0]], columns=CAUSE_COLUMNS)
        assert list(cause_shares(frame).columns) == [f"{c}_share" for c in CAUSE_COLUMNS]

    def test_missing_cause_columns_raise_rather_than_return_empty(self):
        """The old version returned a (n, 0) frame and no error at all.

        A silently empty result is worse than a crash: it propagates into a merge
        or a model as 'no causes recorded' rather than 'you passed the wrong frame'.
        """
        frame = pd.DataFrame({"dtcc": ["0101"], "year": [2019]})
        with pytest.raises(ValueError, match="cause"):
            cause_shares(frame)


class TestFireOccurred:
    def test_flags_the_years_that_burned(self):
        assert fire_occurred(_panel_like()).tolist() == [0, 1, 1, 1]

    def test_threshold_is_respected(self):
        assert fire_occurred(_panel_like(), threshold=25.0).tolist() == [0, 0, 1, 1]

    def test_missing_area_column_raises(self):
        with pytest.raises(ValueError, match="burned_ha_total"):
            fire_occurred(pd.DataFrame({"dtcc": ["0101"], "year": [2019]}))

    def test_refuses_the_pre_2017_era_rather_than_scoring_it_zero(self):
        """`burned_ha_total` is empty before 2017; that era lives in `_ignited`.

        Filling those nulls with zero would label sixteen years of fire history as
        fire-free — a silently wrong ML target, not a missing-data problem.
        """
        pre_2017 = pd.DataFrame({
            "dtcc": ["0101", "0101"],
            "year": [2015, 2016],
            "burned_ha_total": [None, None],
            "burned_ha_total_ignited": [120.0, 340.0],
        })
        with pytest.raises(ValueError, match="2017"):
            fire_occurred(pre_2017)


def test_burn_rate_is_gone_from_features():
    """It duplicated the panel's own `burn_rate`, computed in merge.build_fire_panel.

    Two implementations of one quantity is the drift this package exists to stop.
    """
    import wildfires.features as features

    assert not hasattr(features, "burn_rate")


class TestQuintileData:
    """The slide figures must rebuild from a clean clone.

    quintile_data used to read data/interim/municipal_aging_vs_burn.csv, which is
    gitignored and written by no stage, so scripts/make_presentation_figures.py
    only ran on the machine where that file had been created by hand.
    """

    def test_reads_the_panel_not_a_hand_made_interim_file(self):
        import ast
        import inspect
        import textwrap

        from wildfires import presentation

        # Parse and drop the docstring: it names the old file to explain the
        # change, so a plain substring check over the source would match itself.
        tree = ast.parse(textwrap.dedent(inspect.getsource(presentation.quintile_data)))
        function = tree.body[0]
        if isinstance(function.body[0], ast.Expr) and isinstance(
            function.body[0].value, ast.Constant
        ):
            function.body = function.body[1:]
        body = ast.unparse(function)

        assert "municipal_aging_vs_burn" not in body
        assert "load_panel" in body

    def test_five_quintiles_covering_every_municipality(self):
        from wildfires.config import PATHS

        if not PATHS["processed"]["panel"].exists():
            pytest.skip("panel not built (run make data)")

        from wildfires.presentation import quintile_data

        grouped, rho = quintile_data()
        assert len(grouped) == 5
        assert grouped.n.sum() == 278
        assert -1.0 <= rho <= 1.0

    def test_oldest_quintile_burns_more_than_youngest(self):
        """The claim the slide title makes. If this flips, the title is wrong.

        Deliberately an endpoint comparison, not a monotonicity check: the medians
        are *not* monotone across the five quintiles (Q1 exceeds both Q2 and Q3),
        so asserting a steady rise would fail against correct data.
        """
        from wildfires.config import PATHS

        if not PATHS["processed"]["panel"].exists():
            pytest.skip("panel not built (run make data)")

        from wildfires.presentation import quintile_data

        grouped, _ = quintile_data()
        assert grouped.median_share.iloc[-1] > grouped.median_share.iloc[0]
