"""Shared chart specification for the preliminary-results slides.

Both the static figures and the animated versions are built from this module, so
the two cannot drift apart in colour, ordering, labelling or axis limits.

Source: INE Anuário Estatístico Regional, table II.1.5, "População residente
segundo os grandes grupos etários, de acordo com a Tipologia de áreas urbanas".
The 2022 edition publishes population by município (its table II.1.2) but not the
urban-typology breakdown, so only the rural/urban split is missing for that year.
It is rendered as a break and never interpolated.
"""

from __future__ import annotations

import pandas as pd

from wildfires.ine import TYPOLOGY_LABELS, load_typology_all

# dataviz reference palette, categorical slots 1-3 (light mode). Validated with
# scripts/validate_palette.js: worst all-pairs CVD dE 9.2, normal-vision dE 24.0.
# The aqua sits below 3:1 on the light surface, so the relief rule applies and
# every series carries a visible direct label.
COLORS = {"APU": "#2a78d6", "AMU": "#eb6834", "APR": "#1baf7a"}
ORDER = ["APR", "AMU", "APU"]          # rural first: it is the story
ALL_YEARS = [2019, 2020, 2021, 2022, 2023, 2024]
GAP_YEAR = 2022

TEXT = "#0b0b0b"
MUTED = "#52514e"
GRID = "#ececea"

XLIM = (2018.8, 2024.25)


class ChartSpec:
    """One chart: which column to plot and how to label it."""

    def __init__(self, key: str, value_col: str, title: str, subtitle: str,
                 ylabel: str, fmt) -> None:
        self.key = key
        self.value_col = value_col
        self.title = title
        self.subtitle = subtitle
        self.ylabel = ylabel
        self.fmt = fmt


POPULATION = ChartSpec(
    key="population_change_by_typology",
    value_col="index_2019",
    title="Rural Portugal is losing people while the country grows",
    subtitle="Resident population, indexed to 2019 = 100 · INE Anuário "
             "Estatístico Regional, table II.1.5",
    ylabel="Index (2019 = 100)",
    fmt=lambda v: f"{v:.1f}",
)

AGEING = ChartSpec(
    key="aging_index_by_typology",
    value_col="aging_index",
    title="Rural areas are ageing fastest, from an already old base",
    subtitle="Ageing index: residents aged 65+ per 100 aged 0–14 · INE Anuário "
             "Estatístico Regional, table II.1.5",
    ylabel="Residents 65+ per 100 aged 0–14",
    fmt=lambda v: f"{v:.0f}",
)

CHARTS = [POPULATION, AGEING]


def national_series() -> pd.DataFrame:
    """Portugal totals per typology, reindexed so the missing year is a gap."""
    df = load_typology_all()
    pt = df[df["territory"].str.lower() == "portugal"].copy()
    pt["aging_index"] = 100 * pt["pop_65_plus"] / pt["pop_0_14"]

    out = []
    for typ, grp in pt.groupby("typology"):
        g = grp.set_index("year").reindex(ALL_YEARS)
        g["typology"] = typ
        out.append(g.reset_index().rename(columns={"index": "year"}))
    df = pd.concat(out, ignore_index=True)

    base = df[df.year == 2019].set_index("typology")["pop_total"]
    df["index_2019"] = 100 * df["pop_total"] / df["typology"].map(base)
    return df


def series_for(df: pd.DataFrame, typ: str, value_col: str) -> pd.DataFrame:
    return df[df.typology == typ].sort_values("year")[["year", value_col]]


def y_limits(df: pd.DataFrame, value_col: str, pad: float = 0.10) -> tuple[float, float]:
    """Fixed limits, so an animated reveal does not rescale mid-play."""
    v = df[value_col].dropna()
    lo, hi = float(v.min()), float(v.max())
    margin = (hi - lo) * pad
    return lo - margin, hi + margin


def style_axes(fig, ax, spec: ChartSpec, ylim: tuple[float, float]) -> None:
    """Apply the shared frame: titles at figure level, reserved label margin."""
    fig.subplots_adjust(top=0.80, right=0.735, left=0.075, bottom=0.20)
    fig.text(0.075, 0.935, spec.title, fontsize=16, fontweight="bold",
             color=TEXT, va="bottom")
    fig.text(0.075, 0.885, spec.subtitle, fontsize=9.5, color=MUTED, va="bottom")

    ax.set_ylabel(spec.ylabel, fontsize=10, color=MUTED)
    ax.set_xticks(ALL_YEARS)
    ax.set_xlim(*XLIM)
    ax.set_ylim(*ylim)
    ax.tick_params(colors=MUTED, labelsize=10)
    ax.axvspan(GAP_YEAR - 0.15, GAP_YEAR + 0.15, color=GRID, zorder=0)
    ax.annotate("2022\nurban/rural split\nnot published", xy=(GAP_YEAR, 0.02),
                xycoords=("data", "axes fraction"), ha="center", va="bottom",
                fontsize=8, color=MUTED)


def legend(ax) -> None:
    handles = [
        ax.plot([], [], color=COLORS[t], linewidth=2.4, marker="o", markersize=7,
                markeredgecolor="white", markeredgewidth=1.6,
                label=TYPOLOGY_LABELS[t])[0]
        for t in ORDER
    ]
    ax.legend(handles=handles, frameon=False, fontsize=10, labelcolor=MUTED,
              ncol=3, loc="upper center", bbox_to_anchor=(0.5, -0.09))


def direct_label(ax, typ: str, x: float, y: float, text: str):
    """Label at the line end. Required relief for the low-contrast series."""
    return ax.annotate(f"{TYPOLOGY_LABELS[typ]}\n{text}", xy=(x, y),
                       xytext=(10, 0), textcoords="offset points", va="center",
                       fontsize=9.5, color=TEXT, fontweight="bold",
                       annotation_clip=False)


# ============================================================================
# Bar-based charts. The draw functions take a cutoff so the static figure and
# the animated reveal render through exactly the same code path: the static
# scripts call them with the cutoff wide open, the animation walks it forward.
# ============================================================================

SURFACE = "#fcfcfb"

# --- ICNF fire history, 2001-2025 -------------------------------------------
LAND_TYPES = [
    ("AreaArdPov", "Forest stands", "#2a78d6"),
    ("AreaArdMato", "Scrubland", "#eb6834"),
    ("AreaArdAgric", "Agricultural", "#1baf7a"),
]
COUNT_COLOR = "#0b0b0b"       # a lone count series, deliberately not a category hue
HIGHLIGHT_YEARS = [2003, 2005, 2017, 2025]

FIRE_TITLE = "Portugal has far fewer fires than in 2001 — but not less burned land"
FIRE_SUBTITLE = ("Mainland Portugal, 2001–2025 · ICNF, Estatísticas de Incêndios "
                 "Rurais (SGIF)")


def fire_history_data() -> pd.DataFrame:
    from wildfires.io import load_icnf

    return load_icnf("country").sort_values("year").reset_index(drop=True)


def ignition_drop(df: pd.DataFrame) -> tuple[float, float, float]:
    """Percentage fall in ignitions, first three years against last three."""
    first3 = df.nsmallest(3, "year")["Num_IncendiosRurais"].mean()
    last3 = df.nlargest(3, "year")["Num_IncendiosRurais"].mean()
    return 100 * (1 - last3 / first3), first3, last3


def draw_fire_history(fig, ax_area, ax_count, df: pd.DataFrame,
                      upto: int | None = None) -> None:
    """Render the two-panel fire history, revealing years up to ``upto``."""
    upto = int(df["year"].max()) if upto is None else upto
    shown = df[df["year"] <= upto]

    ax_area.clear()
    ax_count.clear()
    fig.subplots_adjust(top=0.775, right=0.97, left=0.085, bottom=0.10)

    bottom = pd.Series(0.0, index=shown.index)
    for col, label, color in LAND_TYPES:
        ax_area.bar(shown["year"], shown[col] / 1000, bottom=bottom / 1000,
                    label=label, color=color, width=0.72, edgecolor=SURFACE,
                    linewidth=1.1, zorder=3)
        bottom = bottom + shown[col].fillna(0)

    ax_area.set_ylabel("Burned area (thousand ha)", fontsize=10, color=MUTED)
    ax_area.legend(frameon=False, fontsize=9.5, labelcolor=MUTED, ncol=3,
                   loc="lower left", bbox_to_anchor=(0, 1.01))
    ax_area.tick_params(colors=MUTED, labelsize=9.5)
    ax_area.set_ylim(0, df["AreaArdTotal"].max() / 1000 * 1.22)
    ax_area.grid(axis="y", alpha=0.3)

    for y in HIGHLIGHT_YEARS:
        row = shown[shown["year"] == y]
        if row.empty:
            continue
        total = row["AreaArdTotal"].item() / 1000
        ax_area.annotate(f"{y}\n{total:.0f}k ha", xy=(y, total), xytext=(0, 7),
                         textcoords="offset points", ha="center", fontsize=8.5,
                         fontweight="bold", color=TEXT)

    ax_count.plot(shown["year"], shown["Num_IncendiosRurais"] / 1000,
                  color=COUNT_COLOR, linewidth=2.4, marker="o", markersize=5,
                  markeredgecolor="white", markeredgewidth=1.2, zorder=3)
    ax_count.set_ylabel("Rural fires (thousands)", fontsize=10, color=MUTED)
    ax_count.tick_params(colors=MUTED, labelsize=9.5)
    ax_count.set_ylim(0, df["Num_IncendiosRurais"].max() / 1000 * 1.18)
    ax_count.set_xticks(range(2001, 2026, 2))
    ax_count.set_xlim(2000.3, 2025.7)
    ax_count.grid(axis="y", alpha=0.3)

    # The summary only makes sense once the whole series is on screen.
    if upto >= int(df["year"].max()):
        drop, first3, last3 = ignition_drop(df)
        ax_count.annotate(
            f"Ignitions down {drop:.0f}%\n(2001–03 mean {first3/1000:.1f}k → "
            f"2023–25 mean {last3/1000:.1f}k)",
            xy=(0.985, 0.90), xycoords="axes fraction", ha="right", va="top",
            fontsize=9, color=MUTED,
        )


# --- Burned area by ageing quintile -----------------------------------------
# dataviz sequential blue, ordinal steps 250-650. Validated with --ordinal.
RAMP = ["#86b6ef", "#5598e7", "#2a78d6", "#1c5cab", "#104281"]
QUINTILE_LABELS = ["Q1 youngest", "Q2", "Q3", "Q4", "Q5 oldest"]

QUINTILE_TITLE = "Older municipalities burn more of their own land"
QUINTILE_SUBTITLE = ("Share of municipal land area burned 2019–2024 (EFFIS) by "
                     "ageing-index quintile (INE) · 278 mainland municipalities")


def quintile_data():
    """Municipal burn share grouped into ageing-index quintiles, plus Spearman."""
    from wildfires.config import project_root

    cum = pd.read_csv(project_root() / "data/interim/municipal_aging_vs_burn.csv",
                      dtype={"dtcc": str})
    rho = cum["aging"].corr(cum["burnt_share_pct"], method="spearman")
    q = pd.qcut(cum["aging"], 5, labels=QUINTILE_LABELS)
    g = cum.groupby(q, observed=True).agg(
        n=("dtcc", "size"),
        mean_share=("burnt_share_pct", "mean"),
        median_share=("burnt_share_pct", "median"),
        median_aging=("aging", "median"),
    )
    return g, rho


def draw_quintiles(fig, ax, g, rho: float, grown: float | None = None,
                   show_medians: bool = True) -> None:
    """Render the quintile bars. ``grown`` in [0, 5] reveals bars left to right."""
    grown = float(len(g)) if grown is None else grown
    ax.clear()
    fig.subplots_adjust(top=0.78, right=0.97, left=0.08, bottom=0.16)

    heights, medians = [], []
    for i, row in enumerate(g.itertuples()):
        frac = min(max(grown - i, 0.0), 1.0)      # 0 = not started, 1 = full height
        heights.append(row.mean_share * frac)
        medians.append(row.median_share if frac >= 1.0 else None)

    ax.bar(range(len(g)), heights, color=RAMP, width=0.66, zorder=3)

    if show_medians:
        xs = [i for i, m in enumerate(medians) if m is not None]
        ys = [m for m in medians if m is not None]
        ax.scatter(xs, ys, color=TEXT, zorder=5, s=42, marker="D",
                   label="Median municipality")

    for i, (row, h) in enumerate(zip(g.itertuples(), heights, strict=True)):
        if h > 0 and min(max(grown - i, 0.0), 1.0) >= 1.0:
            ax.annotate(f"{row.mean_share:.1f}%", (i, h), xytext=(0, 6),
                        textcoords="offset points", ha="center", fontsize=10,
                        fontweight="bold", color=TEXT)

    ax.set_xticks(
        range(len(g)),
        [f"{lab}\nageing index {a:.0f}"
         for lab, a in zip(QUINTILE_LABELS, g["median_aging"], strict=True)],
        fontsize=10,
    )
    ax.set_ylabel("Mean share of municipal area burned, 2019–2024 (%)",
                  fontsize=10, color=MUTED)
    ax.tick_params(colors=MUTED, labelsize=10)
    ax.set_ylim(0, g["mean_share"].max() * 1.22)
    ax.grid(axis="y", alpha=0.3)
    if show_medians:
        ax.legend(frameon=False, fontsize=10, labelcolor=MUTED, loc="upper left")

    if grown >= len(g):
        ax.annotate(
            f"Spearman ρ = {rho:.2f} — a real but weak gradient.\n"
            f"The median (diamonds) is far below the mean: a few large fires\n"
            f"dominate every quintile.",
            xy=(0.02, 0.72), xycoords="axes fraction", fontsize=9, color=MUTED,
            va="top",
        )


def figure_titles(fig, title: str, subtitle: str, x: float = 0.085,
                  y_title: float = 0.925, y_sub: float = 0.875) -> None:
    fig.text(x, y_title, title, fontsize=16, fontweight="bold", color=TEXT, va="bottom")
    fig.text(x, y_sub, subtitle, fontsize=9.5, color=MUTED, va="bottom")
