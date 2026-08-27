"""Shared code for the Portugal wildfire x demography project.

Notebooks stay thin: they narrate and plot. Anything that transforms data
lives here so that all four chapters read an identical dataset.
"""

from wildfires.config import CONVENTIONS, PATHS, project_root

__all__ = ["PATHS", "CONVENTIONS", "project_root"]
