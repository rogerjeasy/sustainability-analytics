"""Loaders for every raw source in this project.

Each loader returns a tidy frame with predictable column names and applies the
corrections documented in docs/EFFIS_data_dictionary.md, so no notebook has to
remember them.
"""

from __future__ import annotations

import geopandas as gpd
import pandas as pd

from wildfires.config import CRS_GEOGRAPHIC, PATHS, require

# ---------------------------------------------------------------- EFFIS ----

EFFIS_LANDCOVER_COLS = [
    "BROADLEA", "CONIFER", "MIXED", "SCLEROPH", "TRANSIT",
    "OTHERNATLC", "AGRIAREAS", "ARTIFSURF", "OTHERLC",
]


def load_effis_subset(country: str | None = "PT") -> pd.DataFrame:
    """EFFIS burnt-area records for the ES/FR/IT/PT subset (tabular, no geometry).

    Applies two dictionary rules automatically:
      * keeps only ``CLASS == "FireSeason"`` — the other classes are rolling
        near-real-time windows for the current year and get revised;
      * clips ``PERCNA2K`` to 100 (the source maxes at 100.25, a rounding artefact).
    """
    df = pd.read_csv(
        require(PATHS["interim"]["effis_subset"]),
        parse_dates=["FIREDATE", "FINALDATE", "LASTUPDATE"],
        date_format="ISO8601",
    )
    df = df[df["CLASS"] == "FireSeason"].copy()
    if country is not None:
        df = df[df["COUNTRY"] == country].copy()
    df["PERCNA2K"] = df["PERCNA2K"].clip(upper=100)
    df["fire_year"] = df["FIREDATE"].dt.year
    df["duration_days"] = (df["FINALDATE"] - df["FIREDATE"]).dt.total_seconds() / 86400
    return df.reset_index(drop=True)


def load_effis_polygons(country: str | None = "PT") -> gpd.GeoDataFrame:
    """EFFIS burn perimeters with geometry, CRS retagged to EPSG:4326.

    EFFIS ships a ``.prj`` declaring an unnamed WGS84 GEOGCS, which geopandas
    will not recognise as EPSG:4326 without an explicit override.
    """
    gdf = gpd.read_file(require(PATHS["interim"]["effis_subset_geo"]))
    gdf = gdf.set_crs(CRS_GEOGRAPHIC, allow_override=True)
    if country is not None:
        gdf = gdf[gdf["COUNTRY"] == country].copy()
    if "CLASS" in gdf.columns:
        gdf = gdf[gdf["CLASS"] == "FireSeason"].copy()
    return gdf.reset_index(drop=True)


# --------------------------------------------------------------- ICNF ------

# ICNF ships four aggregation levels in one workbook. Concelho is the one that
# joins to demography; the others are convenient cross-checks.
ICNF_SHEETS = {
    "country":  "Estatisticas_PortugalContinent",
    "distrito": "Estatisticas_Distrito",
    "nuts3":    "Estatisticas_NUTS_III",
    "concelho": "Estatisticas_Concelho",
}

ICNF_CAUSE_COLS = [
    "NInc_Natural", "NInc_Negligente", "NInc_Intencionais",
    "NInc_Reacendimentos", "NInc_Desconhecida", "NInc_NaoInvestigados",
]


def load_icnf(level: str = "concelho") -> pd.DataFrame:
    """ICNF fire statistics 2001-2025 at the requested aggregation level.

    ``level="concelho"`` is the project default: it carries ``DTCC``, the
    Portuguese municipality code, which is the panel's join key. It also carries
    the cause breakdown (``NInc_*``) and ``Ninc_Sup24h`` (fires burning longer
    than 24h) that the research questions on fire causes and response depend on.

    The workbook writes missing values as the literal string ``"(sem informação)"``.
    """
    if level not in ICNF_SHEETS:
        raise ValueError(f"level must be one of {sorted(ICNF_SHEETS)}, got {level!r}")

    df = pd.read_excel(
        require(PATHS["raw"]["icnf_statistics"]),
        sheet_name=ICNF_SHEETS[level],
        na_values=["(sem informação)"],
    )
    df.columns = [str(c).strip() for c in df.columns]
    df = df.rename(columns={"Ano": "year", "Região NUTS III (2013)": "nuts3_name"})

    if "DTCC" in df.columns:
        # Zero-pad to 4 digits so it matches GADM's CC_2 ("0101", not 101).
        df["dtcc"] = df["DTCC"].astype("Int64").astype(str).str.zfill(4)

    for col in df.columns:
        if col.startswith(("AreaArd", "NIncRur", "NInc", "Ninc", "Num_")):
            df[col] = pd.to_numeric(df[col], errors="coerce")

    return df


# ---------------------------------------------------------------- INE ------

def load_ine_population(year: int) -> pd.DataFrame:
    """INE Anuário Estatístico Regional population indicators, município level.

    Sheet ``II_01_01`` carries a two-row header (indicator name on one row, unit
    on the next) and four territorial columns (NUTS I/II/III, Município), so the
    header rows are skipped and the columns named explicitly.

    Returns population density and the effective/natural/migratory growth rates —
    the demographic predictors for chapters 03 and 04.
    """
    path = PATHS["raw"]["ine_aer_dir"] / f"AER{year}_II_01.xlsx"
    raw = pd.read_excel(require(path), sheet_name="II_01_01", header=None)

    # Row 3 holds indicator names, row 4 units, data starts at row 5.
    names = raw.iloc[3].tolist()
    df = raw.iloc[5:].copy()
    df.columns = [str(n).strip() if pd.notna(n) else f"col_{i}" for i, n in enumerate(names)]
    df = df.rename(columns={
        "Densidade populacional": "pop_density",
        "Taxa de crescimento efetivo": "growth_effective",
        "Taxa de crescimento natural": "growth_natural",
        "Taxa de crescimento migratório": "growth_migratory",
        "Taxa bruta de natalidade": "birth_rate",
        "Taxa bruta de mortalidade": "death_rate",
    })
    df["ine_year"] = year
    return df.reset_index(drop=True)


def load_ine_population_all(years: range | list[int] | None = None) -> pd.DataFrame:
    """Stack every available AER year into one long frame."""
    if years is None:
        years = [
            int(p.stem[3:7])
            for p in sorted(PATHS["raw"]["ine_aer_dir"].glob("AER*_II_01.xlsx"))
        ]
    return pd.concat([load_ine_population(y) for y in years], ignore_index=True)


# --------------------------------------------------------- Boundaries ------

def load_municipalities(mainland_only: bool = False) -> gpd.GeoDataFrame:
    """GADM level-2 boundaries = the 308 Portuguese concelhos (municipalities).

    ``CC_2`` is the 4-digit municipality code and matches ICNF's ``DTCC``. Join on
    it, never on name: 308 municipalities share only 306 distinct ``NAME_2``
    values, and GADM strips some internal spaces ("CastelodePaiva").

    Two traps this handles:

    * GADM writes the **literal string** ``"NA"`` as the code for 23 Madeira and
      Azores municipalities. Left alone, a join on that string collapses all 23
      into a single row. They are converted to real missing values here.
    * ICNF covers *Portugal Continental* only. Of the 285 coded GADM
      municipalities, 7 are Azorean (codes 41xx/42xx) and have no ICNF
      counterpart, leaving 278 that join cleanly. Pass ``mainland_only=True`` to
      drop the islands up front.
    """
    gdf = gpd.read_file(require(PATHS["raw"]["gadm_municipal"]))
    gdf = gdf.set_crs(CRS_GEOGRAPHIC, allow_override=True)
    gdf = gdf.rename(columns={"CC_2": "dtcc", "NAME_2": "municipality", "NAME_1": "district"})

    gdf["dtcc"] = gdf["dtcc"].replace({"NA": None}).astype("string")

    if mainland_only:
        gdf = gdf[gdf["dtcc"].notna() & ~gdf["dtcc"].str.startswith(("41", "42"))]

    return gdf.reset_index(drop=True)


# ------------------------------------------------------------- Panel ------

def load_panel() -> pd.DataFrame:
    """The analysis-ready (municipality x year) panel.

    This is what chapters 02-04 should read. Built by notebook 01 via
    ``wildfires.merge.build_panel``; run ``make data`` if it is missing.
    """
    return pd.read_parquet(require(PATHS["processed"]["panel"]))
