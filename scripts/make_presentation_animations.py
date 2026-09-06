#!/usr/bin/env python
"""Animated versions of the preliminary-results figures, for the slides.

    reports/figures/population_change_by_typology.gif
    reports/figures/aging_index_by_typology.gif
    reports/figures/fire_history_2001_2025.gif
    reports/figures/burnt_area_by_aging_quintile.gif

The animation is a progressive reveal of the same lines the static PNGs draw —
identical data, palette, axes and labels, taken from wildfires.presentation. The
axes are fixed before the first frame so nothing rescales mid-play, and the
2022 gap stays a gap: the reveal jumps across it rather than drawing through it.

Drop the .gif straight onto a slide (Insert > Pictures). PowerPoint plays it in
slideshow mode. Each GIF plays through exactly once and then rests on the
finished chart — it does not loop.
"""

from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.animation import FuncAnimation, PillowWriter

from wildfires.config import project_root
from wildfires.presentation import (
    CHARTS,
    COLORS,
    FIRE_SUBTITLE,
    FIRE_TITLE,
    ORDER,
    QUINTILE_SUBTITLE,
    QUINTILE_TITLE,
    direct_label,
    draw_fire_history,
    draw_quintiles,
    figure_titles,
    fire_history_data,
    legend,
    national_series,
    quintile_data,
    series_for,
    style_axes,
    y_limits,
)
from wildfires.viz import apply_theme

FPS = 25
DRAW_SECONDS = 3.2       # time spent drawing the lines
HOLD_SECONDS = 0.5       # brief settle; the GIF then rests on this final frame


class PlayOnceWriter(PillowWriter):
    """PillowWriter that emits a GIF which plays once and stops.

    matplotlib's PillowWriter hardcodes ``loop=0``, which means loop forever.
    Omitting the ``loop`` argument entirely makes Pillow skip the Netscape
    looping extension, and every viewer reads its absence as "play once".

    Passing ``loop=1`` is NOT the same thing: that writes an explicit repeat
    count, which many viewers (PowerPoint included) play through twice.
    """

    def finish(self):
        self._frames[0].save(
            self.outfile, save_all=True, append_images=self._frames[1:],
            duration=int(1000 / self.fps))
STEPS_PER_SEGMENT = 60   # interpolation resolution along each year-to-year leg


def _segments(s, value_col):
    """Split a series into contiguous runs, breaking at the missing year.

    Returns a list of (years, values) arrays. The 2022 gap produces two runs,
    which is what keeps the reveal from drawing a line through a year that INE
    never published.
    """
    runs, cur_x, cur_y = [], [], []
    for year, value in zip(s["year"], s[value_col], strict=True):
        if np.isnan(value):
            if len(cur_x) > 0:
                runs.append((np.array(cur_x), np.array(cur_y)))
                cur_x, cur_y = [], []
            continue
        cur_x.append(year)
        cur_y.append(value)
    if cur_x:
        runs.append((np.array(cur_x), np.array(cur_y)))
    return runs


def _densify(runs):
    """Interpolate along each run so the line draws smoothly, not point to point.

    Each run keeps its own dense path; a NaN separator between runs makes
    matplotlib lift the pen across the gap.
    """
    xs, ys, marker_positions = [], [], []
    for i, (rx, ry) in enumerate(runs):
        if i > 0:
            xs.append(np.nan)
            ys.append(np.nan)
        for j in range(len(rx) - 1):
            t = np.linspace(0, 1, STEPS_PER_SEGMENT, endpoint=False)
            xs.extend(rx[j] + t * (rx[j + 1] - rx[j]))
            ys.extend(ry[j] + t * (ry[j + 1] - ry[j]))
        xs.append(rx[-1])
        ys.append(ry[-1])
        # Record where each real data point falls along the dense path.
        for j, (px, py) in enumerate(zip(rx, ry, strict=True)):
            idx = len(xs) - 1 - (len(rx) - 1 - j) * STEPS_PER_SEGMENT
            marker_positions.append((max(idx, 0), px, py))
    return np.array(xs, dtype=float), np.array(ys, dtype=float), marker_positions


def build(spec, df, out_dir):
    apply_theme()
    fig, ax = plt.subplots(figsize=(11, 5.8))
    style_axes(fig, ax, spec, y_limits(df, spec.value_col))
    if spec.value_col == "index_2019":
        ax.axhline(100, color="#b9b9b3", linewidth=1, linestyle="--", zorder=1)
    legend(ax)

    paths, lines, marker_artists, labels = {}, {}, {}, {}
    for typ in ORDER:
        s = series_for(df, typ, spec.value_col)
        xs, ys, markers = _densify(_segments(s, spec.value_col))
        paths[typ] = (xs, ys, markers)

        lines[typ], = ax.plot([], [], color=COLORS[typ], linewidth=2.4, zorder=3)
        marker_artists[typ], = ax.plot([], [], linestyle="none", marker="o",
                                       markersize=7, color=COLORS[typ],
                                       markeredgecolor="white",
                                       markeredgewidth=1.6, zorder=4)
        last = s.dropna().iloc[-1]
        labels[typ] = direct_label(ax, typ, last.year, last[spec.value_col],
                                   spec.fmt(last[spec.value_col]))
        labels[typ].set_alpha(0.0)

    n_path = max(len(paths[t][0]) for t in ORDER)
    draw_frames = int(FPS * DRAW_SECONDS)
    hold_frames = int(FPS * HOLD_SECONDS)

    def update(frame):
        progress = min(frame / max(draw_frames - 1, 1), 1.0)
        cutoff = int(round(progress * n_path))
        for typ in ORDER:
            xs, ys, markers = paths[typ]
            lines[typ].set_data(xs[:cutoff], ys[:cutoff])
            shown = [(px, py) for idx, px, py in markers if idx < cutoff]
            marker_artists[typ].set_data(
                [p[0] for p in shown], [p[1] for p in shown]
            )
            # Fade the end labels in over the last fifth of the draw.
            labels[typ].set_alpha(float(np.clip((progress - 0.8) / 0.2, 0, 1)))
        return list(lines.values()) + list(marker_artists.values()) + list(labels.values())

    anim = FuncAnimation(fig, update, frames=draw_frames + hold_frames,
                         interval=1000 / FPS, blit=False)
    path = out_dir / f"{spec.key}.gif"
    anim.save(path, writer=PlayOnceWriter(fps=FPS), dpi=110)
    plt.close(fig)
    return path


def build_fire_history(out_dir):
    """Reveal the 25-year record chronologically, one year at a time.

    Each frame is a full redraw through the same draw_fire_history() the static
    figure uses, so the animation cannot drift from the PNG.
    """
    apply_theme()
    df = fire_history_data()
    years = sorted(df["year"].unique())

    fig, (ax_area, ax_count) = plt.subplots(
        2, 1, figsize=(11, 7.2), sharex=True,
        gridspec_kw={"height_ratios": [1.5, 1], "hspace": 0.18},
    )
    figure_titles(fig, FIRE_TITLE, FIRE_SUBTITLE)

    frames_per_year = 3
    draw_frames = len(years) * frames_per_year
    hold_frames = int(FPS * HOLD_SECONDS)

    def update(frame):
        idx = min(frame // frames_per_year, len(years) - 1)
        draw_fire_history(fig, ax_area, ax_count, df, upto=years[idx])
        return []

    anim = FuncAnimation(fig, update, frames=draw_frames + hold_frames,
                         interval=1000 / FPS, blit=False)
    path = out_dir / "fire_history_2001_2025.gif"
    anim.save(path, writer=PlayOnceWriter(fps=FPS), dpi=100)
    plt.close(fig)
    return path


def build_quintiles(out_dir):
    """Grow the bars left to right, then settle and show the caveat."""
    apply_theme()
    g, rho = quintile_data()

    fig, ax = plt.subplots(figsize=(11, 5.8))
    figure_titles(fig, QUINTILE_TITLE, QUINTILE_SUBTITLE, x=0.08)

    draw_frames = int(FPS * 3.0)
    hold_frames = int(FPS * HOLD_SECONDS)

    def update(frame):
        progress = min(frame / max(draw_frames - 1, 1), 1.0)
        draw_quintiles(fig, ax, g, rho, grown=progress * len(g))
        return []

    anim = FuncAnimation(fig, update, frames=draw_frames + hold_frames,
                         interval=1000 / FPS, blit=False)
    path = out_dir / "burnt_area_by_aging_quintile.gif"
    anim.save(path, writer=PlayOnceWriter(fps=FPS), dpi=110)
    plt.close(fig)
    return path


def main() -> None:
    out_dir = project_root() / "reports" / "figures"
    out_dir.mkdir(parents=True, exist_ok=True)
    df = national_series()
    outputs = [build(spec, df, out_dir) for spec in CHARTS]
    outputs.append(build_fire_history(out_dir))
    outputs.append(build_quintiles(out_dir))
    for p in outputs:
        print(f"  reports/figures/{p.name}  ({p.stat().st_size/1e6:.1f} MB)")


if __name__ == "__main__":
    main()
