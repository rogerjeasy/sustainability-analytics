"""Shared plot styling and map helpers.

Import ``apply_theme()`` at the top of every chapter so all four sets of figures
look like they belong in one report.
"""

from __future__ import annotations

import matplotlib as mpl
import matplotlib.pyplot as plt

# Sequential ramp for burnt area / intensity, and a categorical set for causes.
FIRE_CMAP = "YlOrRd"
CATEGORICAL = ["#4C72B0", "#DD8452", "#55A868", "#C44E52", "#8172B3", "#937860"]


def apply_theme() -> None:
    """Set project-wide matplotlib defaults."""
    mpl.rcParams.update({
        "figure.figsize": (9, 5),
        "figure.dpi": 110,
        "savefig.dpi": 200,
        "savefig.bbox": "tight",
        "axes.grid": True,
        "axes.grid.axis": "y",
        "grid.alpha": 0.3,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.titlesize": 13,
        "axes.titleweight": "bold",
        "axes.prop_cycle": mpl.cycler(color=CATEGORICAL),
        "font.size": 10,
    })


def save_figure(fig, name: str) -> None:
    """Write a figure to reports/figures/ for reuse in the slides."""
    from wildfires.config import project_root

    out_dir = project_root() / "reports" / "figures"
    out_dir.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_dir / f"{name}.png")


def choropleth(gdf, column: str, title: str = "", ax=None, cmap: str = FIRE_CMAP, **kwargs):
    """Municipality choropleth with consistent styling.

    ``gdf`` must already carry the value column — merge the panel onto the
    boundaries from ``wildfires.io.load_municipalities`` first.
    """
    if ax is None:
        _, ax = plt.subplots(figsize=(6, 8))
    gdf.plot(
        column=column, cmap=cmap, ax=ax, legend=True,
        edgecolor="white", linewidth=0.2,
        missing_kwds={"color": "#eeeeee", "label": "no data"},
        **kwargs,
    )
    ax.set_axis_off()
    if title:
        ax.set_title(title)
    return ax
