#!/usr/bin/env python
"""Build the static preliminary-results figures for the presentation.

    reports/figures/population_change_by_typology.png
    reports/figures/aging_index_by_typology.png
    reports/figures/typology_series.csv     (the numbers behind both charts)

The chart specification lives in wildfires.presentation so that these and the
animated versions cannot drift apart.
"""

from __future__ import annotations

import matplotlib.pyplot as plt

from wildfires.config import project_root
from wildfires.presentation import (
    CHARTS,
    COLORS,
    ORDER,
    direct_label,
    legend,
    national_series,
    series_for,
    style_axes,
    y_limits,
)
from wildfires.viz import apply_theme


def build(spec, df, out_dir):
    fig, ax = plt.subplots(figsize=(11, 5.8))
    style_axes(fig, ax, spec, y_limits(df, spec.value_col))

    if spec.value_col == "index_2019":
        ax.axhline(100, color="#b9b9b3", linewidth=1, linestyle="--", zorder=1)

    for typ in ORDER:
        s = series_for(df, typ, spec.value_col)
        ax.plot(s.year, s[spec.value_col], color=COLORS[typ], linewidth=2.4,
                marker="o", markersize=7, markeredgecolor="white",
                markeredgewidth=1.6, zorder=3)
        last = s.dropna().iloc[-1]
        direct_label(ax, typ, last.year, last[spec.value_col],
                     spec.fmt(last[spec.value_col]))

    legend(ax)
    fig.savefig(out_dir / f"{spec.key}.png")
    plt.close(fig)


def main() -> None:
    apply_theme()
    out_dir = project_root() / "reports" / "figures"
    out_dir.mkdir(parents=True, exist_ok=True)

    df = national_series()
    for spec in CHARTS:
        build(spec, df, out_dir)
        print(f"  reports/figures/{spec.key}.png")

    table = df[["year", "typology", "pop_total", "pop_0_14", "pop_65_plus",
                "aging_index", "index_2019"]].sort_values(["typology", "year"])
    table.to_csv(out_dir / "typology_series.csv", index=False)
    print("  reports/figures/typology_series.csv")


if __name__ == "__main__":
    main()
