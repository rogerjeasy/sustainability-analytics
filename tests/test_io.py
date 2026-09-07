"""Tests for the processed-panel loaders the analysis notebooks read."""

from __future__ import annotations

import pandas as pd
import pytest

from wildfires import io as wildfires_io
from wildfires.config import PATHS


def test_load_fire_panel_reads_the_built_artifact(tmp_path, monkeypatch):
    target = tmp_path / "fire_panel.parquet"
    pd.DataFrame({"dtcc": ["0101"], "year": [2001], "n_fires": [3.0]}).to_parquet(
        target, index=False
    )
    monkeypatch.setitem(PATHS["processed"], "fire_panel", target)

    frame = wildfires_io.load_fire_panel()
    assert list(frame.columns) == ["dtcc", "year", "n_fires"]
    assert len(frame) == 1


def test_load_fire_panel_says_how_to_build_it_when_missing(tmp_path, monkeypatch):
    """A bare FileNotFoundError sends the reader hunting; name the command."""
    monkeypatch.setitem(PATHS["processed"], "fire_panel", tmp_path / "absent.parquet")

    with pytest.raises(FileNotFoundError, match="make data"):
        wildfires_io.load_fire_panel()


def test_load_panel_says_how_to_build_it_when_missing(tmp_path, monkeypatch):
    monkeypatch.setitem(PATHS["processed"], "panel", tmp_path / "absent.parquet")

    with pytest.raises(FileNotFoundError, match="make data"):
        wildfires_io.load_panel()
