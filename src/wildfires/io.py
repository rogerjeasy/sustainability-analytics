"""Loaders for every raw source in this project.

Each loader returns a tidy frame with predictable column names and applies the
corrections documented in docs/EFFIS_data_dictionary.md, so no notebook has to
remember them.
"""

from __future__ import annotations

from pathlib import Path
from shutil import copy2
from tempfile import gettempdir

import geopandas as gpd
import pandas as pd

from wildfires.config import CRS_GEOGRAPHIC, PATHS, require
from wildfires.clean import normalise_dtcc

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

    source = require(PATHS["raw"]["icnf_statistics"])
    try:
        df = pd.read_excel(
            source,
            sheet_name=ICNF_SHEETS[level],
            na_values=["(sem informação)"],
        )
    except PermissionError:
        # OneDrive can deny direct reads while still allowing a local copy.
        local_copy = Path(gettempdir()) / source.name
        if not local_copy.is_file():
            copy2(source, local_copy)
        df = pd.read_excel(
            local_copy,
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

def load_municipality_dimensions() -> pd.DataFrame:
    """Load municipality areas from the data.gov.pt 2022 dimensions table."""
    df = pd.read_csv(
        require(PATHS["raw"]["municipality_dimensions"]),
        encoding="latin1",
        parse_dates=["Data de Referência"],
    )
    df = df.rename(columns={
        "Data de Referência": "reference_date",
        "Superfície (km2)": "area_km2",
        "Código Concelho": "dtcc",
        "Designação Concelho": "municipality",
        "Código Distrito": "district_code",
        "Designação Distrito": "district",
        "Código NUTSIII": "nuts3_code",
        "Designação NUTSIII": "nuts3",
        "Código NUTSII": "nuts2_code",
        "Designação NUTSII": "nuts2",
    })
    df["dtcc"] = normalise_dtcc(df["dtcc"])
    df["area_km2"] = pd.to_numeric(df["area_km2"], errors="coerce")
    return df.reset_index(drop=True)

def load_ine_population(year: int) -> pd.DataFrame:
    """INE Anuário Estatístico Regional population indicators, município level.

    Sheet ``II_01_01`` carries a two-row header (indicator name on one row, unit
    on the next), with an extra title row in some years.

    Returns population density and the effective/natural/migratory growth rates —
    the demographic predictors for chapters 03 and 04.
    """
    path = PATHS["raw"]["ine_aer_dir"] / f"AER{year}_II_01.xlsx"
    raw = pd.read_excel(require(path), sheet_name="II_01_01", header=None)

    header_row = next(
        index
        for index, row in raw.iterrows()
        if any(str(value).strip().startswith("Densidade populacional") for value in row)
    )
    names = raw.iloc[header_row].tolist()
    df = raw.iloc[header_row + 2:].copy()
    columns = []
    occurrences: dict[str, int] = {}
    for index, name in enumerate(names):
        column = str(name).strip() if pd.notna(name) else f"col_{index}"
        occurrence = occurrences.get(column, 0)
        occurrences[column] = occurrence + 1
        columns.append(column if occurrence == 0 else f"{column}_{occurrence}")
    df.columns = columns
    df = df.rename(columns={"col_0": "municipality"})
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


def load_ine_population_age(year: int, *, _sheet: str | None = None) -> pd.DataFrame:
    """Load resident population totals and age groups by municipality and sex.

    The main table is ``II_01_03`` before and after 2022, and ``II_01_02`` in
    2022. Older workbooks split the older age groups into companion ``...c``
    sheets, which are merged by municipality. The AER tables are
    municipality-level; they do not provide freguesia rows.
    """
    path = PATHS["raw"]["ine_aer_dir"] / f"AER{year}_II_01.xlsx"
    workbook = pd.ExcelFile(require(path))
    primary_sheets = ["II_01_02", "II_01_02c"] if year == 2022 else ["II_01_03", "II_01_03c"]
    expected_sheets = primary_sheets
    sheet = _sheet or next((name for name in primary_sheets if name in workbook.sheet_names), None)
    if sheet is None:
        raise ValueError(
            f"Expected one of {expected_sheets!r} in {path.name}; "
            f"found {workbook.sheet_names}"
        )

    if _sheet is None:
        companion = next((name for name in primary_sheets[1:] if name in workbook.sheet_names), None)
        if companion is not None:
            main = load_ine_population_age(year, _sheet=sheet)
            extra = load_ine_population_age(year, _sheet=companion)
            age_columns = [
                "25-64 anos",
                "65 e mais anos__Total",
                "75 e mais anos",
            ]
            keys = ["municipality"] + (["dtcc"] if "dtcc" in main and "dtcc" in extra else [])
            return main.merge(extra[keys + age_columns], on=keys, how="left", validate="one_to_one")

    raw = pd.read_excel(workbook, sheet_name=sheet, header=None)
    data_start = next(
        index
        for index, value in raw.iloc[:, 0].items()
        if str(value).strip() == "Portugal"
    )
    header_rows = raw.iloc[max(0, data_start - 3):data_start]
    labels = []
    for column_index in range(raw.shape[1]):
        parts = []
        for value in header_rows.iloc[:, column_index]:
            text = str(value).strip()
            if text not in {"", "nan", "HM", "H", "M"} and text not in parts:
                parts.append(text)
        labels.append("__".join(parts) or f"col_{column_index}")

    columns = []
    occurrences: dict[str, int] = {}
    for index, label in enumerate(labels):
        occurrence = occurrences.get(label, 0)
        occurrences[label] = occurrence + 1
        columns.append(label if occurrence == 0 else f"{label}_{occurrence}")

    df = raw.iloc[data_start:].copy()
    df.columns = columns
    df = df.rename(columns={columns[0]: "municipality"})
    municipality_flag = next((column for column in df.columns if column == "Município"), None)
    code_column = next(
        (column for column in df.columns if column in {"DTMN", "NUTS_2013", "NUTS_DTMN", "NUTS_2024"}),
        None,
    )
    if municipality_flag is not None:
        df = df[df[municipality_flag].eq("x")].copy()
    elif code_column is not None:
        codes = df[code_column].astype(str).str.strip()
        df = df[codes.str.fullmatch(r"\d{4}") & codes.ne("0000")].copy()
    if code_column is not None:
        codes = df[code_column].astype(str).str.strip()
        df["dtcc"] = codes.str[-4:].str.zfill(4)

    # The workbook layout changed between years: age groups may be split into
    # HM/H/M columns, and territorial columns were renamed with NUTS 2024.
    # Keep the first total (HM) column for each group so yearly concatenation
    # has one stable schema instead of one column per workbook layout.
    age_groups = [
        "Total",
        "0 a 14 anos",
        "15 a 24 anos",
        "25-64 anos",
        "65 e mais anos__Total",
        "75 e mais anos",
    ]
    selected = ["municipality"]
    if "dtcc" in df:
        selected.append("dtcc")
    for age_group in age_groups:
        candidates = [
            column
            for column in df.columns
            if column == age_group or column.startswith(f"{age_group}__")
        ]
        if not candidates:
            continue
        preferred = next(
            (column for column in candidates if column == age_group), candidates[0]
        )
        if preferred != age_group:
            df = df.rename(columns={preferred: age_group})
        selected.append(age_group)
    df = df[selected].copy()
    for column in age_groups:
        if column not in df:
            continue
        df[column] = pd.to_numeric(df[column], errors="coerce")
    df["ine_year"] = year
    df["geo_level"] = "municipality"
    return df.reset_index(drop=True)


def load_ine_population_age_all(years: range | list[int] | None = None) -> pd.DataFrame:
    """Stack resident population age tables for the requested AER years."""
    if years is None:
        years = [
            int(path.stem[3:7])
            for path in sorted(PATHS["raw"]["ine_aer_dir"].glob("AER*_II_01.xlsx"))
        ]
    return pd.concat([load_ine_population_age(year) for year in years], ignore_index=True)


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
