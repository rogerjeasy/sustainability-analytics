#!/usr/bin/env python
"""ICNF 25-year fire history for the presentation.

    reports/figures/fire_history_2001_2025.png
    reports/figures/fire_history_2001_2025.csv

Source: ICNF, EstatisticasIncendiosSGIF-2001-2025, sheet
"Estatisticas_PortugalContinent" (mainland Portugal, complete 2001-2025).

Two measures move in opposite directions, so they get two stacked panels sharing
one x-axis — never two y-scales on one plot. The drawing itself lives in
wildfires.presentation so the animated version renders identically.
"""

from __future__ import annotations

import matplotlib.pyplot as plt

from wildfires.config import project_root
from wildfires.presentation import (
    FIRE_SUBTITLE,
    FIRE_TITLE,
    draw_fire_history,
    figure_titles,
    fire_history_data,
    ignition_drop,
)
from wildfires.viz import apply_theme


def main() -> None:
    apply_theme()
    out_dir = project_root() / "reports" / "figures"
    out_dir.mkdir(parents=True, exist_ok=True)

    df = fire_history_data()

    fig, (ax_area, ax_count) = plt.subplots(
        2, 1, figsize=(11, 7.2), sharex=True,
        gridspec_kw={"height_ratios": [1.5, 1], "hspace": 0.18},
    )
    figure_titles(fig, FIRE_TITLE, FIRE_SUBTITLE)
    draw_fire_history(fig, ax_area, ax_count, df)
    fig.savefig(out_dir / "fire_history_2001_2025.png")
    plt.close(fig)

    keep = ["year", "Num_IncendiosRurais", "AreaArdPov", "AreaArdMato",
            "AreaArdAgric", "AreaArdTotal", "Ninc_Sup24h",
            "NInc_Natural", "NInc_Negligente", "NInc_Intencionais",
            "NInc_Reacendimentos", "NInc_Desconhecida", "NInc_NaoInvestigados"]
    df[[c for c in keep if c in df.columns]].to_csv(
        out_dir / "fire_history_2001_2025.csv", index=False)

    drop, first3, last3 = ignition_drop(df)
    print("  reports/figures/fire_history_2001_2025.png")
    print("  reports/figures/fire_history_2001_2025.csv")
    print(f"  ignitions down {drop:.1f}% ({first3:,.0f} -> {last3:,.0f})")


if __name__ == "__main__":
    main()
