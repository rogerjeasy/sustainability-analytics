#!/usr/bin/env python
"""Check which raw inputs are present and print how to obtain the missing ones.

Several sources (ICNF, INE, EFFIS) sit behind manual download forms with no
stable direct URL, so this reports and instructs rather than silently fetching.
Run it after cloning: `make data`.
"""

from __future__ import annotations

import sys

from wildfires.config import PATHS, project_root

SOURCES = {
    "EFFIS burnt-area polygons": (
        PATHS["raw"]["effis_polygons"],
        "https://forest-fire.emergency.copernicus.eu/applications/data-and-services\n"
        "  Request access, then download the burnt-area layer as SHAPEZIP and\n"
        "  unpack into data/raw/effis/.",
    ),
    "ICNF fire statistics 2001-2025": (
        PATHS["raw"]["icnf_statistics"],
        "https://www.icnf.pt/florestas/gfr/gfrgestaoinformacao/estatisticas\n"
        "  Download 'EstatisticasIncendiosSGIF' into data/raw/icnf/.",
    ),
    "INE regional yearbooks (AER)": (
        PATHS["raw"]["ine_aer_dir"],
        "https://www.ine.pt -> Anuario Estatistico Regional, chapter II.01\n"
        "  Save AER<year>_II_01.xlsx into data/raw/ine/.",
    ),
    "GADM municipal boundaries": (
        PATHS["raw"]["gadm_municipal"],
        "https://gadm.org/download_country.html -> Portugal -> level 2 GeoJSON\n"
        "  Save as data/raw/boundaries/gadm41_PRT_2.json.",
    ),
    "Weather (ERA5-Land)": (
        PATHS["raw"]["weather_dir"],
        "NOT YET ACQUIRED. Register at https://cds.climate.copernicus.eu, then\n"
        "  retrieve ERA5-Land monthly means for Portugal into data/raw/weather/.\n"
        "  Registration approval takes time - start this early.",
    ),
}


def main() -> int:
    root = project_root()
    missing = 0
    for name, (path, instructions) in SOURCES.items():
        present = path.exists() and (any(path.iterdir()) if path.is_dir() else True)
        mark = "OK     " if present else "MISSING"
        print(f"[{mark}] {name}\n           {path.relative_to(root)}")
        if not present:
            missing += 1
            print("           " + instructions.replace("\n", "\n           "))
        print()

    print(f"{len(SOURCES) - missing}/{len(SOURCES)} sources present.")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
