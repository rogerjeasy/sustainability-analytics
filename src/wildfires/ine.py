"""INE Anuário Estatístico Regional — resident population by age group.

Source sheets (table II.1.3, renumbered II.1.2 in the 2022 edition):

    "População residente por município, segundo os grandes grupos etários
     e o sexo em 31/12"

The layout changes between editions, so each year is described explicitly
below rather than guessed at:

* **2019-2022** split the age groups across two sheets. The main sheet carries
  Total / 0-14 / 15-24; the ``c`` continuation sheet carries 25-64 / 65+ / 75+.
  Reading only the main sheet silently loses every elderly count.
* **2023-2024** carry all age groups in a single sheet.
* Header rows and the territorial-code columns move between editions too.

Every value returned here is read from the workbook. Nothing is imputed.
"""

from __future__ import annotations

import pandas as pd

from wildfires.config import PATHS, require

# year -> (sheet, group_header_row, sex_header_row, first_data_row, territorial cols)
# Column indices are 0-based positions in the raw sheet.
_MAIN = "main"
_CONT = "cont"

SHEET_SPEC: dict[int, dict] = {
    2019: {
        _MAIN: ("II_01_03", 3, 4, 5),
        _CONT: ("II_01_03c", 3, 4, 5),
        "code_col": 12,          # NUTS_DTMN, the 7-char hierarchical code
        "name_cols": {},         # 2019 has no NUTS name columns
    },
    2020: {
        _MAIN: ("II_01_03", 4, 5, 6),
        _CONT: ("II_01_03c", 4, 5, 6),
        "code_col": 11,          # NUTS_2013
        "name_cols": {"nuts1": 12, "nuts2": 13, "nuts3": 14, "municipality": 15},
    },
    2021: {
        _MAIN: ("II_01_03", 4, 5, 6),
        _CONT: ("II_01_03c", 4, 5, 6),
        "code_col": 11,
        "name_cols": {"nuts1": 12, "nuts2": 13, "nuts3": 14, "municipality": 15},
    },
    2022: {
        _MAIN: ("II_01_02", 4, 5, 6),
        _CONT: ("II_01_02c", 4, 5, 6),
        "code_col": 11,          # NUTS_DTMN
        "name_cols": {"nuts1": 12, "nuts2": 13, "nuts3": 14, "municipality": 15},
    },
    2023: {
        _MAIN: ("II_01_03", 4, 5, 6),
        _CONT: None,             # single sheet
        "code_col": 20,
        "name_cols": {"nuts1": 21, "nuts2": 22, "nuts3": 23, "municipality": 24},
    },
    2024: {
        _MAIN: ("II_01_03", 4, 5, 6),
        _CONT: None,
        "code_col": 20,
        "name_cols": {"nuts1": 21, "nuts2": 22, "nuts3": 23, "municipality": 24},
    },
}

# Age-group columns (HM = both sexes) by position, per sheet role.
_MAIN_AGE_COLS_SPLIT = {"pop_total": 1, "pop_0_14": 4, "pop_15_24": 7}
_CONT_AGE_COLS       = {"pop_25_64": 1, "pop_65_plus": 4, "pop_75_plus": 7}
_SINGLE_AGE_COLS     = {
    "pop_total": 1, "pop_0_14": 4, "pop_15_24": 7,
    "pop_25_64": 10, "pop_65_plus": 13, "pop_75_plus": 16,
}


def _read_sheet(year: int, sheet: str, first_row: int, age_cols: dict,
                code_col: int | None, name_cols: dict) -> pd.DataFrame:
    path = PATHS["raw"]["ine_aer_dir"] / f"AER{year}_II_01.xlsx"
    raw = pd.read_excel(require(path), sheet_name=sheet, header=None)
    body = raw.iloc[first_row:].copy()

    out = pd.DataFrame({"territory": body[0].astype("string").str.strip()})
    for name, pos in age_cols.items():
        out[name] = pd.to_numeric(body[pos], errors="coerce")
    if code_col is not None and code_col < raw.shape[1]:
        out["code"] = body[code_col].astype("string").str.strip()
    for name, pos in name_cols.items():
        if pos < raw.shape[1]:
            out[name] = body[pos].astype("string").str.strip()

    # Drop the footnote block at the bottom. Each sheet is filtered on its own
    # first age column, so the main and continuation sheets keep the same rows.
    anchor = next(iter(age_cols))
    return out[out["territory"].notna() & out[anchor].notna()].reset_index(drop=True)


def load_population_year(year: int) -> pd.DataFrame:
    """Resident population by territory and broad age group, for one AER edition.

    Returns both-sexes (HM) counts only — that is what the aging measures need.
    """
    spec = SHEET_SPEC[year]
    main_sheet, _, _, first_row = spec[_MAIN]

    if spec[_CONT] is None:
        df = _read_sheet(year, main_sheet, first_row, _SINGLE_AGE_COLS,
                         spec["code_col"], spec["name_cols"])
    else:
        cont_sheet, _, _, cont_first = spec[_CONT]
        main = _read_sheet(year, main_sheet, first_row, _MAIN_AGE_COLS_SPLIT,
                           spec["code_col"], spec["name_cols"])
        cont = _read_sheet(year, cont_sheet, cont_first, _CONT_AGE_COLS, None, {})
        # Both sheets list the identical territory rows in the identical order.
        if len(main) != len(cont):
            raise ValueError(
                f"AER{year}: main sheet has {len(main)} rows but continuation has "
                f"{len(cont)} — the two sheets no longer align, refusing to guess."
            )
        cont = cont.drop(columns="territory").reset_index(drop=True)
        df = pd.concat([main.reset_index(drop=True), cont], axis=1)

    df["year"] = year
    return df


def load_population_all(years: list[int] | None = None) -> pd.DataFrame:
    """Stack every AER edition into one long frame, one row per territory-year."""
    years = sorted(SHEET_SPEC) if years is None else years
    return pd.concat([load_population_year(y) for y in years], ignore_index=True)


def add_aging_measures(df: pd.DataFrame) -> pd.DataFrame:
    """Add the standard INE aging indicators, computed from the counts.

    ``aging_index`` is INE's *índice de envelhecimento*: residents aged 65+ per
    100 residents aged 0-14. ``old_age_dependency`` is 65+ per 100 aged 15-64.
    """
    out = df.copy()
    out["share_65_plus"] = 100 * out["pop_65_plus"] / out["pop_total"]
    out["share_0_14"] = 100 * out["pop_0_14"] / out["pop_total"]
    out["aging_index"] = 100 * out["pop_65_plus"] / out["pop_0_14"]
    working = out["pop_15_24"] + out["pop_25_64"]
    out["old_age_dependency"] = 100 * out["pop_65_plus"] / working
    return out


def add_territory_level(df: pd.DataFrame) -> pd.DataFrame:
    """Label each row as country / nuts3 / municipality / other.

    Municipalities are identified from the hierarchical code, which is
    unambiguous: a 7-character code whose last four characters are not ``0000``
    (``1111601`` = Arcos de Valdevez).

    NUTS3 needs more care. The 2019 edition pads every code to 7 characters,
    which makes NUTS2 ``15`` and NUTS3 ``150`` both read as ``1500000`` — and
    Algarve, A.M. Lisboa, Açores and Madeira are single-region NUTS2s where that
    collision is real, not a parsing artefact. So NUTS3 rows are taken from the
    explicit ``x`` flag columns that the 2020+ editions carry, and the 2019 rows
    are recovered by matching territory names against that flagged set.
    """
    out = df.copy()
    code = out["code"].fillna("").astype(str).str.strip()
    territory = out["territory"].fillna("").astype(str).str.strip()

    is_muni = (code.str.len() == 7) & (code.str[3:] != "0000")

    def _flag(col: str) -> pd.Series:
        if col not in out.columns:
            return pd.Series(False, index=out.index)
        return out[col].fillna("").astype(str).str.strip().str.lower().eq("x")

    flagged_nuts3 = _flag("nuts3") & ~_flag("municipality")
    # 2019 carries no flag columns; recover it by name from the flagged years.
    known_names = set(territory[flagged_nuts3])
    by_name = territory.isin(known_names) & ~is_muni

    is_nuts3 = flagged_nuts3 | by_name

    out["level"] = "other"
    out.loc[is_nuts3, "level"] = "nuts3"
    out.loc[is_muni, "level"] = "municipality"
    out.loc[territory.str.lower() == "portugal", "level"] = "country"
    return out


# --- Table II.1.5: population by age group and urban typology, by NUTS3 ------
#
# INE's typology (Tipologia de áreas urbanas):
#   APU  Área Predominantemente Urbana      predominantly urban
#   AMU  Área Mediamente Urbana             intermediate
#   APR  Área Predominantemente Rural       predominantly rural
#
# The 2022 edition does not contain this table: it publishes municipality-level
# population (its table II.1.2, which load_population_year does read) but drops
# the urban-typology breakdown in favour of foreign-population tables. So 2022 is
# absent here only, and must be shown as a gap, never interpolated.
TYPOLOGY_SHEET: dict[int, tuple[str, int]] = {
    2019: ("II_01 05", 5),   # (sheet name, first data row)
    2020: ("II_01 05", 6),
    2021: ("II_01 05", 6),
    2023: ("II_01_05", 6),
    2024: ("II_01_05", 6),
}

# Column positions are identical in every edition: three typology columns per
# age group, in APU / AMU / APR order.
_TYPOLOGY_COLS = {
    "pop_0_14":    {"APU": 1, "AMU": 2, "APR": 3},
    "pop_15_24":   {"APU": 4, "AMU": 5, "APR": 6},
    "pop_25_64":   {"APU": 7, "AMU": 8, "APR": 9},
    "pop_65_plus": {"APU": 10, "AMU": 11, "APR": 12},
}

TYPOLOGY_LABELS = {
    "APU": "Predominantly urban",
    "AMU": "Intermediate",
    "APR": "Predominantly rural",
}


def load_typology_year(year: int) -> pd.DataFrame:
    """Population by age group and urban typology for one AER edition.

    Returns long format: one row per (territory, typology).
    """
    sheet, first_row = TYPOLOGY_SHEET[year]
    path = PATHS["raw"]["ine_aer_dir"] / f"AER{year}_II_01.xlsx"
    raw = pd.read_excel(require(path), sheet_name=sheet, header=None)
    body = raw.iloc[first_row:]

    frames = []
    for typ in ("APU", "AMU", "APR"):
        block = pd.DataFrame({"territory": body[0].astype("string").str.strip()})
        for age, cols in _TYPOLOGY_COLS.items():
            block[age] = pd.to_numeric(body[cols[typ]], errors="coerce")
        block["typology"] = typ
        block["year"] = year
        frames.append(block[block["territory"].notna() & block["pop_0_14"].notna()])

    return pd.concat(frames, ignore_index=True)


def load_typology_all(years: list[int] | None = None) -> pd.DataFrame:
    """Stack every edition that carries table II.1.5.

    2022 is absent from the source and therefore absent here.
    """
    years = sorted(TYPOLOGY_SHEET) if years is None else years
    df = pd.concat([load_typology_year(y) for y in years], ignore_index=True)
    df["pop_total"] = (
        df["pop_0_14"] + df["pop_15_24"] + df["pop_25_64"] + df["pop_65_plus"]
    )
    return df
