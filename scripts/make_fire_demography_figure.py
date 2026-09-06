#!/usr/bin/env python
"""Combined EFFIS x INE slide: burned area against demographic ageing.

    reports/figures/burnt_area_by_aging_quintile.png
    reports/figures/municipal_aging_vs_burn.csv

EFFIS burn perimeters are spatially joined to municipality (GADM level 2), summed
over 2019-2024 and expressed as a share of each municipality's own land area.
Municipalities are then grouped into quintiles of mean ageing index from INE.

Both mean and median are drawn, because they disagree: burned area is heavily
skewed, and the mean alone would overstate how clean the gradient is.
"""

from __future__ import annotations

import matplotlib.pyplot as plt
import pandas as pd

from wildfires.config import project_root
from wildfires.presentation import (
    QUINTILE_SUBTITLE,
    QUINTILE_TITLE,
    draw_quintiles,
    figure_titles,
    quintile_data,
)
from wildfires.viz import apply_theme


def main() -> None:
    apply_theme()
    out_dir = project_root() / "reports" / "figures"
    out_dir.mkdir(parents=True, exist_ok=True)

    g, rho = quintile_data()

    fig, ax = plt.subplots(figsize=(11, 5.8))
    figure_titles(fig, QUINTILE_TITLE, QUINTILE_SUBTITLE, x=0.08)
    draw_quintiles(fig, ax, g, rho)
    fig.savefig(out_dir / "burnt_area_by_aging_quintile.png")
    plt.close(fig)

    cum = pd.read_csv(project_root() / "data/interim/municipal_aging_vs_burn.csv",
                      dtype={"dtcc": str})
    cum.to_csv(out_dir / "municipal_aging_vs_burn.csv", index=False)

    print(f"  reports/figures/burnt_area_by_aging_quintile.png  (Spearman rho={rho:.3f})")
    print(g.round(2).to_string())


if __name__ == "__main__":
    main()
