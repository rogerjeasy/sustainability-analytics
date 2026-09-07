# Data Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Two commands — `make fetch` and `make data` — take a fresh clone to an analysis-ready municipality-year panel for the statistics and ML chapters.

**Architecture:** A committed manifest (`config/sources.yml`) drives checksum-verified downloads from a GitHub Release (small workbooks) and a public Google Drive folder (EFFIS). Four ordered preprocessing stages write one artifact each, from `data/raw` through `data/interim` to two `data/processed` panels plus a NUTS III typology side table. A validation stage refuses to emit a panel that violates its row-count, key-uniqueness or null-rate contract.

**Tech Stack:** Python 3.11, pandas 2.2+, geopandas 1.0+, openpyxl, pyarrow, PyYAML, pytest, ruff. No new runtime dependencies beyond `requests` (already implied by the environment; add explicitly).

**Spec:** `docs/superpowers/specs/2026-09-06-data-pipeline-design.md`

## Global Constraints

- Join key is `dtcc`, the 4-character zero-padded municipality code. Never join on name.
- Granularity of every output is one row per `(dtcc, year)`.
- **Nothing is imputed, interpolated or smoothed.** Missing stays missing. INE conventional signs (`x`, `…`, `§`, `ə`, `//`) become `NaN`; `┴` (break in series) is recorded as metadata, never used to alter values.
- The joined panel covers 2019–2024 only (INE AER availability), 278 mainland municipalities, 1,668 rows.
- The fire panel covers 2001–2025, 6,921 rows; municipality count per year rises from 270 (2001) to 278 (2006 onward). Never assert a flat 278 × 25 product.
- ICNF's two burned-area conventions are **strictly complementary, with no overlap year**: `AreaArd*_IncendioInicioConc` is populated 2001–2016 only, `AreaArd*_NoConcelho` 2017–2025 only. They are distinct measures, must never be coalesced, and no burned-area series spans 2001–2025 on one definition.
- Tests must not require network access or the 565 MB EFFIS files. EFFIS-dependent tests skip when raw files are absent.
- Line length 100 (ruff). `make lint` and `make test` must pass before each commit.
- Repo is public: the release must attribute INE and ICNF.

---

## File Structure

**Create:**
- `config/sources.yml` — the only place a download URL or checksum appears
- `src/wildfires/fetch.py` — checksum verification and the HTTP / Google Drive downloaders
- `src/wildfires/pipeline.py` — the four preprocessing stages
- `src/wildfires/validate.py` — panel contract checks and the Markdown report
- `scripts/fetch_data.py` — CLI for `make fetch`
- `scripts/build_data.py` — CLI for `make data`
- `tests/test_fetch.py`, `tests/test_pipeline.py`, `tests/test_validate.py`

**Modify:**
- `src/wildfires/ine.py` — becomes the single INE reader; gains the `II_01_01`/`_01c` indicator loader
- `src/wildfires/io.py` — loses all INE functions and `load_municipality_dimensions`
- `src/wildfires/merge.py` — completes `build_panel`, gains `build_fire_panel`
- `config/paths.yml` — drop `municipality_dimensions`; add new outputs
- `Makefile`, `README.md`, `data/README.md`, `docs/data_dictionary.md`
- `tests/test_ine.py`, `tests/test_merge.py`

**Delete:**
- `scripts/download_data.py` (absorbed as `fetch_data.py --check`)

---

## Task 1: INE indicator loader with sign-stripped header matching

Reads `II_01_01` and `II_01_01c` — the only municipality-level source for density, growth rates and birth/death rates.

**Why name-based lookup is mandatory** (measured, do not "simplify" to fixed positions):
`II_01_01` indicator positions happen to be stable (cols 1–6 every year), but `II_01_01c` shifts: `Índice de envelhecimento` sits at col 3 in 2019/2020/2021/2024 and col 4 in 2022/2023, because the 2022 edition inserts `Idade mediana da população residente` and the 2024 edition drops `População estrangeira…`.

**Files:**
- Modify: `src/wildfires/ine.py`
- Test: `tests/test_ine.py`

**Interfaces:**
- Consumes: `wildfires.config.PATHS`, `require`
- Produces:
  - `normalise_indicator(name: object) -> str`
  - `load_indicators_year(year: int) -> pd.DataFrame` — columns `territory`, `code`, `pop_density`, `growth_effective`, `growth_natural`, `growth_migratory`, `birth_rate`, `death_rate`, `aging_index_ine`, `renewal_index`, `old_age_dependency_ine`, `longevity_index`, `year`
  - `load_indicators_all(years: list[int] | None = None) -> pd.DataFrame`
  - `series_breaks(years: list[int] | None = None) -> pd.DataFrame` — columns `year`, `sheet`, `indicator`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_ine.py`:

```python
from wildfires.ine import (
    load_indicators_all,
    load_indicators_year,
    normalise_indicator,
    series_breaks,
)


class TestNormaliseIndicator:
    def test_strips_break_in_series_marker(self):
        # AER2021 writes 'Densidade populacional \n┴'. The trailing sign is why
        # an exact-string match silently drops pop_density for 2021 alone.
        assert normalise_indicator("Densidade populacional \n┴") == "Densidade populacional"

    def test_strips_other_conventional_signs(self):
        assert normalise_indicator("Taxa bruta de natalidade §") == "Taxa bruta de natalidade"

    def test_collapses_internal_whitespace(self):
        assert normalise_indicator("Índice  de\nlongevidade") == "Índice de longevidade"


class TestIndicators:
    def test_pop_density_present_for_every_edition(self):
        """Regression: the 2021 break-in-series marker must not drop the column."""
        df = load_indicators_all()
        muni = df[df.code.str.len().eq(7) & df.code.str[3:].ne("0000")]
        counts = muni.groupby("year").pop_density.notna().sum()
        assert (counts > 0).all(), f"pop_density missing for {counts[counts == 0].index.tolist()}"

    def test_all_six_rate_columns_populated_every_year(self):
        df = load_indicators_all()
        for col in ("pop_density", "growth_effective", "growth_natural",
                    "growth_migratory", "birth_rate", "death_rate"):
            per_year = df.groupby("year")[col].notna().sum()
            assert (per_year > 0).all(), f"{col} empty in {per_year[per_year == 0].index.tolist()}"

    def test_dependency_index_uses_the_real_ine_label(self):
        """INE writes 'de idosas/os', not 'de idosos'. Wrong label = silent all-null."""
        df = load_indicators_year(2024)
        assert df.old_age_dependency_ine.notna().any()

    def test_continuation_columns_survive_position_shift(self):
        """II_01_01c shifts columns between editions; name lookup must absorb it."""
        for year in (2019, 2022, 2024):
            df = load_indicators_year(year)
            assert df.aging_index_ine.notna().any(), f"aging index lost in {year}"
            assert df.longevity_index.notna().any(), f"longevity lost in {year}"

    def test_308_municipalities_every_year(self):
        df = load_indicators_all()
        muni = df[df.code.str.len().eq(7) & df.code.str[3:].ne("0000")]
        assert set(muni.groupby("year").size()) == {308}

    def test_missing_markers_become_nan_not_strings(self):
        df = load_indicators_all()
        assert df.pop_density.map(lambda v: isinstance(v, str)).sum() == 0


class TestSeriesBreaks:
    def test_records_the_2021_density_break(self):
        breaks = series_breaks()
        row = breaks[(breaks.year == 2021) & (breaks.sheet == "II_01_01")]
        assert "Densidade populacional" in set(row.indicator)

    def test_records_the_2022_life_expectancy_breaks(self):
        breaks = series_breaks()
        got = set(breaks[(breaks.year == 2022) & (breaks.sheet == "II_01_01c")].indicator)
        assert "Esperança de vida à nascença" in got
        assert "Esperança de vida aos 65 anos" in got

    def test_breaks_do_not_alter_values(self):
        """The flag is metadata. 2021 density must still carry real numbers."""
        df = load_indicators_year(2021)
        assert df.pop_density.notna().sum() > 300
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_ine.py -k "Indicator or SeriesBreaks or NormaliseIndicator" -v`
Expected: FAIL with `ImportError: cannot import name 'normalise_indicator'`

- [ ] **Step 3: Implement the loader**

Add to `src/wildfires/ine.py`:

```python
import re

# INE conventional signs, defined in each workbook's Sinais_Signs sheet. They are
# appended to header cells as well as values, which is why indicator names must be
# normalised before matching. '┴' means quebra de serie (break in series) and is
# captured as metadata by series_breaks(); it never changes a value.
INE_SIGNS = ("┴", "§", "…", "ə", "//")

# Sheet II_01_01: municipality-level population indicators. Positions are stable
# across editions, but names are matched anyway so a future insert cannot shift them.
INDICATORS_MAIN = {
    "Densidade populacional": "pop_density",
    "Taxa de crescimento efetivo": "growth_effective",
    "Taxa de crescimento natural": "growth_natural",
    "Taxa de crescimento migratório": "growth_migratory",
    "Taxa bruta de natalidade": "birth_rate",
    "Taxa bruta de mortalidade": "death_rate",
}

# Sheet II_01_01c: positions genuinely move between editions (2022 inserts
# 'Idade mediana da populacao residente'; 2024 drops the foreign-population column),
# so these MUST be located by name.
INDICATORS_CONT = {
    "Índice de envelhecimento": "aging_index_ine",
    "Índice de renovação da população em idade ativa": "renewal_index",
    "Índice de dependência de idosas/os": "old_age_dependency_ine",
    "Índice de longevidade": "longevity_index",
}

_CODE_HEADERS = {"DTMN", "NUTS_DTMN", "NUTS_2013", "NUTS_2024"}


def normalise_indicator(name: object) -> str:
    """Strip INE conventional signs and collapse whitespace in a header cell."""
    text = str(name)
    for sign in INE_SIGNS:
        text = text.replace(sign, "")
    return re.sub(r"\s+", " ", text).strip()


def _open_sheet(year: int, sheet: str) -> pd.DataFrame:
    path = PATHS["raw"]["ine_aer_dir"] / f"AER{year}_II_01.xlsx"
    return pd.read_excel(require(path), sheet_name=sheet, header=None)


def _header_row(raw: pd.DataFrame, mapping: dict[str, str]) -> int:
    wanted = set(mapping)
    for index, row in raw.iterrows():
        if wanted & {normalise_indicator(value) for value in row}:
            return index
    raise ValueError(f"No header row carrying any of {sorted(wanted)}")


def _first_data_row(raw: pd.DataFrame) -> int:
    """Portugal is the first territory in every AER table."""
    for index, value in raw.iloc[:, 0].items():
        if str(value).strip() == "Portugal":
            return index
    raise ValueError("No 'Portugal' row found; sheet layout changed")


def _code_column(raw: pd.DataFrame, header_row: int, first_data: int) -> int:
    """Locate the 7-digit hierarchical code column.

    Its header moved across editions: DTMN/NUTS_DTMN (2019), NUTS_2013 (2020-2022),
    NUTS_2024 (2023-2024). The rightmost match is the 7-digit one; 2019 also carries
    a 4-digit DTMN column immediately to its left.
    """
    found = None
    for index in range(header_row, first_data):
        for position, value in enumerate(raw.iloc[index]):
            if normalise_indicator(value) in _CODE_HEADERS:
                found = position
    if found is None:
        raise ValueError(f"No column among {sorted(_CODE_HEADERS)} above row {first_data}")
    return found


def _read_indicator_sheet(year: int, sheet: str, mapping: dict[str, str]) -> pd.DataFrame:
    raw = _open_sheet(year, sheet)
    header_row = _header_row(raw, mapping)
    first_data = _first_data_row(raw)
    names = [normalise_indicator(value) for value in raw.iloc[header_row]]
    body = raw.iloc[first_data:]

    out = pd.DataFrame({
        "territory": body[0].astype("string").str.strip(),
        "code": body[_code_column(raw, header_row, first_data)].astype("string").str.strip(),
    })
    for label, column in mapping.items():
        # to_numeric turns the 'x' / '…' / '§' missing markers into NaN, as documented
        # in Sinais_Signs. Absent indicators stay absent rather than being invented.
        out[column] = (
            pd.to_numeric(body[names.index(label)], errors="coerce")
            if label in names else pd.NA
        )
    return out[out["territory"].notna()].reset_index(drop=True)


def load_indicators_year(year: int) -> pd.DataFrame:
    """Municipality-level population indicators for one AER edition."""
    main = _read_indicator_sheet(year, "II_01_01", INDICATORS_MAIN)
    cont = _read_indicator_sheet(year, "II_01_01c", INDICATORS_CONT)
    merged = main.merge(
        cont.drop(columns="territory"), on="code", how="outer", validate="one_to_one"
    )
    merged["year"] = year
    return merged


def load_indicators_all(years: list[int] | None = None) -> pd.DataFrame:
    """Stack the population indicators of every AER edition."""
    years = sorted(SHEET_SPEC) if years is None else years
    return pd.concat([load_indicators_year(y) for y in years], ignore_index=True)


def series_breaks(years: list[int] | None = None) -> pd.DataFrame:
    """Every indicator INE flags with '┴' (quebra de serie / break in series).

    2021 flags 'Densidade populacional' — the Censos 2021 re-basing — so density is
    not strictly comparable across 2020 -> 2021. Recorded, never corrected for.
    """
    years = sorted(SHEET_SPEC) if years is None else years
    rows = []
    for year in years:
        for sheet, mapping in (("II_01_01", INDICATORS_MAIN), ("II_01_01c", INDICATORS_CONT)):
            raw = _open_sheet(year, sheet)
            header = raw.iloc[_header_row(raw, mapping)]
            for value in header:
                if "┴" in str(value):
                    rows.append({
                        "year": year, "sheet": sheet,
                        "indicator": normalise_indicator(value),
                    })
    return pd.DataFrame(rows, columns=["year", "sheet", "indicator"])
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_ine.py -v`
Expected: PASS, including the pre-existing population tests.

- [ ] **Step 5: Lint and commit**

```bash
ruff check src tests
git add src/wildfires/ine.py tests/test_ine.py
git commit -m "Add INE population-indicator loader with sign-stripped headers

Sheet II_01_01/_01c is the only municipality-level source for population
density, growth rates and crude birth/death rates.

Indicators are located by name, not position: II_01_01c shifts columns
between editions (2022 inserts a median-age column, 2024 drops the
foreign-population one). Header cells carry INE conventional signs, and
the break-in-series marker on the 2021 density header is why an exact
string match dropped pop_density for that year alone.

Break-in-series flags are captured as metadata; values are untouched."
```

---

## Task 2: Consolidate INE reading into ine.py

`io.py` and `ine.py` currently both parse INE age sheets with different strategies. `ine.py` is the one that is verified correct (308 municipalities every edition, age groups reproduce INE's own printed Total). This removes the duplicate and the stale `municipality_dimensions` path.

**Files:**
- Modify: `src/wildfires/io.py` (delete `load_ine_population`, `load_ine_population_all`, `load_ine_population_age`, `load_ine_population_age_all`, `load_municipality_dimensions`)
- Modify: `config/paths.yml` (drop `raw.municipality_dimensions`)
- Test: `tests/test_ine.py`

**Interfaces:**
- Consumes: Task 1's `load_indicators_all`
- Produces: `wildfires.io` exports no INE symbol; `wildfires.ine` is the sole INE reader.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_ine.py`:

```python
class TestSingleINEReader:
    def test_io_exposes_no_ine_loaders(self):
        """One reader, not two. Duplicated parsers drift and disagree silently."""
        import wildfires.io as io_module

        leaked = [n for n in dir(io_module) if "ine_population" in n]
        assert leaked == [], f"io.py still exports INE loaders: {leaked}"

    def test_io_drops_the_nonexistent_dimensions_loader(self):
        """raw/dimensions/superficies-por-concelho-2022.csv is not on disk.

        Municipality area comes from GADM geometry in EPSG:3763 instead.
        """
        import wildfires.io as io_module

        assert not hasattr(io_module, "load_municipality_dimensions")

    def test_paths_no_longer_declares_municipality_dimensions(self):
        from wildfires.config import PATHS

        assert "municipality_dimensions" not in PATHS["raw"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_ine.py -k SingleINEReader -v`
Expected: FAIL — `io.py still exports INE loaders: ['load_ine_population', ...]`

- [ ] **Step 3: Delete the duplicates**

In `src/wildfires/io.py` remove these five functions entirely: `load_municipality_dimensions`, `load_ine_population`, `load_ine_population_all`, `load_ine_population_age`, `load_ine_population_age_all`. Keep every EFFIS, ICNF and boundary function.

Remove the now-unused import if `normalise_dtcc` is no longer referenced in `io.py`; run `ruff check src` to confirm.

In `config/paths.yml`, delete this line from the `raw:` block:

```yaml
  municipality_dimensions: data/raw/dimensions/superficies-por-concelho-2022.csv
```

- [ ] **Step 4: Run the full suite**

Run: `pytest -q && ruff check src tests`
Expected: PASS. If any notebook or script imported a deleted function, `ruff` will not catch it — grep first:

```bash
grep -rn "load_ine_population\|load_municipality_dimensions" --include=*.py --include=*.ipynb . | grep -v _build
```

Repoint any hit at `wildfires.ine.load_indicators_all` or `wildfires.ine.load_population_all`.

- [ ] **Step 5: Commit**

```bash
git add src/wildfires/io.py config/paths.yml tests/test_ine.py
git commit -m "Consolidate INE reading into ine.py

io.py and ine.py both parsed the INE age sheets with different
strategies. ine.py is the verified one: 308 municipalities in every
edition, and the parsed age groups reproduce INE's own printed Total.

Also drops load_municipality_dimensions and its paths.yml entry: that
CSV is not on disk, and municipality area comes from GADM geometry in
EPSG:3763 instead."
```

---

## Task 3: Source manifest and checksum verification

**Files:**
- Create: `config/sources.yml`
- Create: `src/wildfires/fetch.py`
- Test: `tests/test_fetch.py`

**Interfaces:**
- Produces:
  - `load_manifest() -> list[Source]` where `Source` is a dataclass with fields `name: str`, `kind: str`, `target: Path`, `sha256: str`, `bytes: int`, `url: str | None`, `file_id: str | None`, `instructions: str | None`
  - `sha256_of(path: Path) -> str`
  - `verify(source: Source) -> str` returning one of `"ok"`, `"missing"`, `"corrupt"`

- [ ] **Step 1: Write `config/sources.yml`**

Checksums are the real values computed from the current working copies. The `url` fields for `github_release` entries are filled in by Task 6; write them now with the tag that Task 6 creates.

```yaml
# The single source of truth for every raw input. `make fetch` reads only this.
#
# kind:
#   http    direct download from a stable URL
#   gdrive  public Google Drive file id (handles the large-file confirm token)
#   manual  no scriptable route; print instructions and fail
#
# sha256 values are computed from the working copies used to build the panel.
# A mismatch is a hard failure: a truncated download must not silently produce
# a broken panel.

release_tag: v0.1-data
release_repo: rogerjeasy/sustainability-analytics
gdrive_folder: https://drive.google.com/drive/folders/1PQkPYVMMe8UIoFqVLtuh9PdQolV-Fvxd

sources:
  - name: EFFIS burnt-area polygons (.shp)
    kind: gdrive
    file_id: 1MvgxfKz0ABNwO5V6m2ip3ld33W25DmWm
    target: data/raw/effis/modis.ba.poly.shp
    bytes: 323262544
    sha256: f4a66dce6f917c94cf6d9fa951cb2fbf5f475062615f5fad5dd13e8fa17ad0f8

  - name: EFFIS burnt-area attributes (.dbf)
    kind: gdrive
    file_id: 14e9uKnH3rehHK4QowhxFr-U8Ov-8iwi9
    target: data/raw/effis/modis.ba.poly.dbf
    bytes: 159932271
    sha256: 78bb22a258b82ddfbcfccd6d09595d553ed7d9614fbba33b87b4331fa15b6c97

  - name: EFFIS burnt-area index (.shx)
    kind: gdrive
    file_id: 1OMn_snhrRoTgL466F7KiM480DY7ZuIvS
    target: data/raw/effis/modis.ba.poly.shx
    bytes: 841292
    sha256: 96059cb00c726244057afca385b39256f9e9d10aa6b88c73a931ab01ec07d81a

  - name: EFFIS burnt-area projection (.prj)
    kind: gdrive
    file_id: 1b49mWOtu-QxEm1dYr14-VeNvt8UXSuLG
    target: data/raw/effis/modis.ba.poly.prj
    bytes: 144
    sha256: c69b41ee32e7bda0958c84e843bb5dc34c29130c356129f66448a1ed2364ceb7

  - name: EFFIS severity raster 2023
    kind: gdrive
    file_id: 1uQOJGXVLq_74DLXaOnJGlLqNEcZC3SK-
    target: data/raw/effis/severity_2023.tiff
    bytes: 103839354
    sha256: e533b09e5fcbc0640f5cdcda03959163636e1ce2c44816f64e2c02435829ae96

  - name: ICNF rural fire statistics 2001-2025
    kind: http
    url: https://github.com/rogerjeasy/sustainability-analytics/releases/download/v0.1-data/EstatisticasIncendiosSGIF-2001-2025.xlsx
    target: data/raw/icnf/EstatisticasIncendiosSGIF-2001-2025.xlsx
    bytes: 1265335
    sha256: 598e16b3a16ca398aee2f90e8ec5baef627d4d6eeb792db6892990030fc31a84

  - name: INE AER 2019 chapter II.01
    kind: http
    url: https://github.com/rogerjeasy/sustainability-analytics/releases/download/v0.1-data/AER2019_II_01.xlsx
    target: data/raw/ine/AER2019_II_01.xlsx
    bytes: 346501
    sha256: c373405379a48afc701cf07b5857b26202c75b275746253dc66041d526601dcc

  - name: INE AER 2020 chapter II.01
    kind: http
    url: https://github.com/rogerjeasy/sustainability-analytics/releases/download/v0.1-data/AER2020_II_01.xlsx
    target: data/raw/ine/AER2020_II_01.xlsx
    bytes: 368632
    sha256: ccc158e91755709fae315fe0856c95b2dd236a5b54b365a2597440ac8732490b

  - name: INE AER 2021 chapter II.01
    kind: http
    url: https://github.com/rogerjeasy/sustainability-analytics/releases/download/v0.1-data/AER2021_II_01.xlsx
    target: data/raw/ine/AER2021_II_01.xlsx
    bytes: 357501
    sha256: e89bc0a57dde8d25ce922beafe7c2cd72bcbe2bd80ca711a5994b917c551bfa3

  - name: INE AER 2022 chapter II.01
    kind: http
    url: https://github.com/rogerjeasy/sustainability-analytics/releases/download/v0.1-data/AER2022_II_01.xlsx
    target: data/raw/ine/AER2022_II_01.xlsx
    bytes: 339174
    sha256: 0c31ead751c1082eb54ebef231cc82bfdc8d4d14daea3eea99719232447c97b0

  - name: INE AER 2023 chapter II.01
    kind: http
    url: https://github.com/rogerjeasy/sustainability-analytics/releases/download/v0.1-data/AER2023_II_01.xlsx
    target: data/raw/ine/AER2023_II_01.xlsx
    bytes: 333809
    sha256: 5fa79e8801e9ec1c81e9575c64a74109560385624dde22a24911dbd41e9a113a

  - name: INE AER 2024 chapter II.01
    kind: http
    url: https://github.com/rogerjeasy/sustainability-analytics/releases/download/v0.1-data/AER2024_II_01.xlsx
    target: data/raw/ine/AER2024_II_01.xlsx
    bytes: 294984
    sha256: 8ae389f2e075ddd7d59822d9569c041462907c7d8bb4ed28fa467756e609ae73

  - name: GADM level-2 municipal boundaries
    kind: http
    url: https://geodata.ucdavis.edu/gadm/gadm4.1/json/gadm41_PRT_2.json.zip
    target: data/raw/boundaries/gadm41_PRT_2.json
    unzip_member: gadm41_PRT_2.json
    bytes: 939819
    sha256: 1c23bb359e23ddc8f5eddad22bdc35ddbef3caf93420a267ca998f0db551965e
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_fetch.py`:

```python
"""Tests for the source manifest and checksum verification.

These never touch the network: they exercise manifest parsing and hashing on
temporary files.
"""

from __future__ import annotations

import pytest

from wildfires.fetch import load_manifest, sha256_of, verify


class TestManifest:
    def test_every_source_has_target_and_checksum(self):
        for source in load_manifest():
            assert source.target is not None, f"{source.name} has no target"
            assert len(source.sha256) == 64, f"{source.name} has a malformed sha256"
            assert source.bytes > 0, f"{source.name} has no size"

    def test_every_source_has_a_route(self):
        for source in load_manifest():
            if source.kind == "http":
                assert source.url, f"{source.name} is http but has no url"
            elif source.kind == "gdrive":
                assert source.file_id, f"{source.name} is gdrive but has no file_id"
            elif source.kind == "manual":
                assert source.instructions, f"{source.name} is manual but has no instructions"
            else:
                pytest.fail(f"{source.name} has unknown kind {source.kind!r}")

    def test_names_are_unique(self):
        names = [s.name for s in load_manifest()]
        assert len(names) == len(set(names))

    def test_targets_are_unique(self):
        targets = [s.target for s in load_manifest()]
        assert len(targets) == len(set(targets))


class TestSha256:
    def test_matches_known_digest(self, tmp_path):
        # sha256 of the empty string, the standard test vector.
        path = tmp_path / "empty"
        path.write_bytes(b"")
        expected = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        assert sha256_of(path) == expected


class TestVerify:
    def _source(self, tmp_path, payload, digest):
        from wildfires.fetch import Source

        target = tmp_path / "f.bin"
        if payload is not None:
            target.write_bytes(payload)
        return Source(name="t", kind="http", target=target, sha256=digest,
                      bytes=len(payload or b""), url="http://x", file_id=None,
                      instructions=None, unzip_member=None)

    def test_missing_file(self, tmp_path):
        assert verify(self._source(tmp_path, None, "0" * 64)) == "missing"

    def test_matching_file_is_ok(self, tmp_path):
        payload = b"hello"
        digest = "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
        assert verify(self._source(tmp_path, payload, digest)) == "ok"

    def test_wrong_content_is_corrupt(self, tmp_path):
        """A truncated download must fail loudly, not produce a broken panel."""
        assert verify(self._source(tmp_path, b"hello", "0" * 64)) == "corrupt"
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `pytest tests/test_fetch.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'wildfires.fetch'`

- [ ] **Step 4: Implement manifest loading and verification**

Create `src/wildfires/fetch.py`:

```python
"""Checksum-verified acquisition of every raw input.

The manifest at config/sources.yml is the only place a URL or checksum appears.
Downloads are verified against it, so a truncated or wrong-version file fails
loudly instead of silently producing a broken panel.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import yaml

from wildfires.config import project_root

MANIFEST_RELPATH = Path("config") / "sources.yml"
_CHUNK = 1 << 20


@dataclass(frozen=True)
class Source:
    name: str
    kind: str
    target: Path
    sha256: str
    bytes: int
    url: str | None = None
    file_id: str | None = None
    instructions: str | None = None
    unzip_member: str | None = None


def manifest_path() -> Path:
    return project_root() / MANIFEST_RELPATH


def _config() -> dict:
    with manifest_path().open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def load_manifest() -> list[Source]:
    """Every declared source, with targets resolved against the repository root."""
    root = project_root()
    return [
        Source(
            name=entry["name"],
            kind=entry["kind"],
            target=root / entry["target"],
            sha256=entry["sha256"],
            bytes=entry["bytes"],
            url=entry.get("url"),
            file_id=entry.get("file_id"),
            instructions=entry.get("instructions"),
            unzip_member=entry.get("unzip_member"),
        )
        for entry in _config()["sources"]
    ]


def sha256_of(path: Path) -> str:
    """Streaming digest — these files reach 300 MB and must not be slurped."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def verify(source: Source) -> str:
    """Return 'ok', 'missing' or 'corrupt' for one source."""
    if not source.target.exists():
        return "missing"
    return "ok" if sha256_of(source.target) == source.sha256 else "corrupt"
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/test_fetch.py -v`
Expected: PASS

- [ ] **Step 6: Verify the manifest against the real files on disk**

Run:

```bash
python -c "
from wildfires.fetch import load_manifest, verify
for s in load_manifest():
    print(f'{verify(s):8s} {s.name}')
"
```

Expected: `ok` for all 13 sources. Any `corrupt` means a checksum in the manifest is wrong — recompute with `shasum -a256`, do not adjust the file.

- [ ] **Step 7: Commit**

```bash
git add config/sources.yml src/wildfires/fetch.py tests/test_fetch.py
git commit -m "Add source manifest with checksum verification

config/sources.yml is the single place a download URL or checksum
appears. Checksums are computed from the working copies that produced
the panel, so a truncated download fails loudly rather than yielding a
silently broken result."
```

---

## Task 4: HTTP and Google Drive downloaders

Google Drive serves files above roughly 100 MB behind a "Virus scan warning" interstitial. **Verified behavior** (do not simplify away):

- Small files: `https://drive.google.com/uc?export=download&id=<id>` returns bytes directly.
- Large files: the same URL returns `text/html` containing a form with `id`, `export=download`, `confirm=t` and a `uuid`. Re-requesting `https://drive.usercontent.google.com/download` with those four parameters returns the real bytes and answers range requests with `206`, so downloads resume.

**Files:**
- Modify: `src/wildfires/fetch.py`
- Test: `tests/test_fetch.py`

**Interfaces:**
- Consumes: Task 3's `Source`, `verify`, `sha256_of`
- Produces:
  - `parse_drive_confirm(html: str) -> dict[str, str]` — the form fields, empty dict when the response is not an interstitial
  - `download(source: Source, *, force: bool = False) -> str` returning `"ok"`, `"skipped"` or `"failed"`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_fetch.py`:

```python
INTERSTITIAL = (
    '<!DOCTYPE html><html><head><title>Google Drive - Virus scan warning</title>'
    '</head><body><form action="https://drive.usercontent.google.com/download" '
    'method="get"><input type="hidden" name="id" value="ABC123">'
    '<input type="hidden" name="export" value="download">'
    '<input type="hidden" name="confirm" value="t">'
    '<input type="hidden" name="uuid" value="40f24b61-a56c-465f-b969-2690b12295c2">'
    '</form></body></html>'
)


class TestDriveConfirm:
    def test_extracts_every_form_field(self):
        from wildfires.fetch import parse_drive_confirm

        fields = parse_drive_confirm(INTERSTITIAL)
        assert fields["id"] == "ABC123"
        assert fields["confirm"] == "t"
        assert fields["uuid"] == "40f24b61-a56c-465f-b969-2690b12295c2"
        assert fields["export"] == "download"

    def test_binary_payload_is_not_mistaken_for_an_interstitial(self):
        """Shapefile bytes start 0000270a and must not parse as a confirm page."""
        from wildfires.fetch import parse_drive_confirm

        assert parse_drive_confirm("\x00\x00\x27\x0a binary junk") == {}

    def test_plain_html_without_a_form_yields_nothing(self):
        from wildfires.fetch import parse_drive_confirm

        assert parse_drive_confirm("<html><body>not a form</body></html>") == {}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_fetch.py -k DriveConfirm -v`
Expected: FAIL with `ImportError: cannot import name 'parse_drive_confirm'`

- [ ] **Step 3: Implement the downloaders**

Append to `src/wildfires/fetch.py`:

```python
import re
import shutil
import zipfile
from tempfile import NamedTemporaryFile

import requests

DRIVE_DIRECT = "https://drive.google.com/uc?export=download&id={file_id}"
DRIVE_CONFIRM = "https://drive.usercontent.google.com/download"
_TIMEOUT = 60
_FORM_INPUT = re.compile(r'name="([^"]+)"\s+value="([^"]*)"')


class ChecksumMismatch(RuntimeError):
    """A download completed but did not match the manifest digest."""


def parse_drive_confirm(html: str) -> dict[str, str]:
    """Extract the confirm-form fields from Drive's virus-scan interstitial.

    Returns an empty dict when the payload is not an interstitial, so binary
    file content is never mistaken for a form.
    """
    if "Virus scan warning" not in html and "<form" not in html:
        return {}
    fields = dict(_FORM_INPUT.findall(html))
    return fields if {"id", "confirm"} <= set(fields) else {}


def _stream_to(response: requests.Response, destination: Path, expected: str) -> None:
    """Stream to a sibling temp file, hashing as we go, and only then rename.

    Renaming after the digest matches means an interrupted or corrupted fetch can
    never leave a half-written file sitting where a valid one belongs.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    with NamedTemporaryFile(dir=destination.parent, delete=False) as tmp:
        temp_path = Path(tmp.name)
        for chunk in response.iter_content(chunk_size=_CHUNK):
            tmp.write(chunk)
            digest.update(chunk)

    if digest.hexdigest() != expected:
        actual = digest.hexdigest()
        temp_path.unlink()
        raise ChecksumMismatch(f"expected {expected}, got {actual}")
    temp_path.replace(destination)


def _download_http(source: Source) -> None:
    with requests.get(source.url, stream=True, timeout=_TIMEOUT) as response:
        response.raise_for_status()
        if source.unzip_member:
            with NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
                archive = Path(tmp.name)
                for chunk in response.iter_content(chunk_size=_CHUNK):
                    tmp.write(chunk)
            source.target.parent.mkdir(parents=True, exist_ok=True)
            extracted = source.target.with_suffix(source.target.suffix + ".part")
            with zipfile.ZipFile(archive) as zf, \
                 zf.open(source.unzip_member) as member, \
                 extracted.open("wb") as out:
                shutil.copyfileobj(member, out)
            archive.unlink()
            if sha256_of(extracted) != source.sha256:
                extracted.unlink()
                raise ChecksumMismatch(f"{source.name}: extracted member does not match")
            extracted.replace(source.target)
        else:
            _stream_to(response, source.target, source.sha256)


def _download_gdrive(source: Source) -> None:
    """Fetch a public Drive file, following the large-file confirm token."""
    with requests.Session() as session:
        url = DRIVE_DIRECT.format(file_id=source.file_id)
        response = session.get(url, stream=True, timeout=_TIMEOUT)
        response.raise_for_status()

        if response.headers.get("Content-Type", "").startswith("text/html"):
            fields = parse_drive_confirm(response.text)
            if not fields:
                raise RuntimeError(
                    f"{source.name}: Drive returned HTML with no confirm form. "
                    "Is the folder still shared publicly?"
                )
            response = session.get(DRIVE_CONFIRM, params=fields,
                                   stream=True, timeout=_TIMEOUT)
            response.raise_for_status()

        _stream_to(response, source.target, source.sha256)


def download(source: Source, *, force: bool = False) -> str:
    """Fetch one source and verify it. Returns 'ok', 'skipped' or 'failed'."""
    if not force and verify(source) == "ok":
        return "skipped"

    if source.kind == "manual":
        print(f"  {source.name} must be fetched by hand:\n    {source.instructions}")
        return "failed"
    try:
        if source.kind == "http":
            _download_http(source)
        elif source.kind == "gdrive":
            _download_gdrive(source)
        else:
            raise ValueError(f"Unknown source kind {source.kind!r}")
    except ChecksumMismatch as exc:
        print(f"  CHECKSUM MISMATCH for {source.name}\n    {exc}\n"
              "    The partial file was discarded. Re-run; if it recurs the "
              "upstream copy changed and the manifest needs updating.")
        return "failed"
    except requests.RequestException as exc:
        print(f"  DOWNLOAD FAILED for {source.name}: {exc}")
        return "failed"
    return "ok"
```

Add `requests` to `environment.yml` (conda-forge) and `requirements.txt`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_fetch.py -v && ruff check src tests`
Expected: PASS

- [ ] **Step 5: Prove the Drive path works end to end on the smallest real file**

```bash
mv data/raw/effis/modis.ba.poly.prj /tmp/prj.backup
python -c "
from wildfires.fetch import load_manifest, download
s = next(s for s in load_manifest() if s.target.name == 'modis.ba.poly.prj')
print(download(s))
"
```

Expected: prints `ok` (checksum verified against the manifest). Confirm identity, then restore:

```bash
diff data/raw/effis/modis.ba.poly.prj /tmp/prj.backup && echo "identical" && rm /tmp/prj.backup
```

- [ ] **Step 6: Commit**

```bash
git add src/wildfires/fetch.py tests/test_fetch.py environment.yml requirements.txt
git commit -m "Add HTTP and Google Drive downloaders

Drive serves files above ~100MB behind a virus-scan interstitial. The
confirm-token flow is followed to drive.usercontent.google.com, which
returns the real bytes. Binary payloads are never mistaken for a form.

Downloads stream to a temporary file and are renamed into place only
after the checksum matches, so an interrupted fetch cannot leave a
half-written file that looks valid."
```

---

## Task 5: fetch CLI and Makefile target

**Files:**
- Create: `scripts/fetch_data.py`
- Delete: `scripts/download_data.py`
- Modify: `Makefile`

**Interfaces:**
- Consumes: Task 3–4's `load_manifest`, `verify`, `download`
- Produces: `make fetch`, `make fetch-check`

- [ ] **Step 1: Write the CLI**

Create `scripts/fetch_data.py`:

```python
#!/usr/bin/env python
"""Fetch every raw input declared in config/sources.yml.

    make fetch          download whatever is missing or corrupt
    make fetch-check    report status only, download nothing

Downloads are verified against committed checksums, so a truncated or
wrong-version file fails loudly rather than silently producing a broken panel.
"""

from __future__ import annotations

import argparse
import sys

from wildfires.config import project_root
from wildfires.fetch import download, load_manifest, verify

_MARK = {"ok": "OK     ", "missing": "MISSING", "corrupt": "CORRUPT"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="report status only; download nothing")
    parser.add_argument("--force", action="store_true",
                        help="re-download even when the local file verifies")
    parser.add_argument("--only", metavar="SUBSTRING",
                        help="restrict to sources whose target path contains this")
    args = parser.parse_args()

    root = project_root()
    sources = load_manifest()
    if args.only:
        sources = [s for s in sources if args.only in str(s.target)]
        if not sources:
            print(f"No source matches --only {args.only!r}")
            return 1

    failed = 0
    for source in sources:
        state = verify(source)
        relative = source.target.relative_to(root)

        if args.check:
            print(f"[{_MARK[state]}] {source.name}\n           {relative}")
            failed += state != "ok"
            continue

        if state == "ok" and not args.force:
            print(f"[OK     ] {source.name}")
            continue

        size_mb = source.bytes / 1_000_000
        print(f"[FETCH  ] {source.name}  ({size_mb:.1f} MB)")
        if download(source, force=args.force) != "ok":
            failed += 1

    total = len(sources)
    print(f"\n{total - failed}/{total} sources ready.")
    if failed:
        print("Re-run `make fetch` to retry. See data/README.md for provenance.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Replace the old script and wire up the Makefile**

```bash
git rm scripts/download_data.py
```

In `Makefile`, replace the `data` target and extend `help`:

```makefile
.PHONY: help setup fetch fetch-check data panel test lint report report-serve clean-report

help:
	@echo "setup       - create the conda env and install pre-commit hooks"
	@echo "fetch       - download every raw input (checksum-verified, ~565 MB)"
	@echo "fetch-check - report which raw inputs are present, download nothing"
	@echo "data        - build interim + processed datasets from data/raw"
	@echo "panel       - alias for 'data'"
	@echo "test        - run pytest"
	@echo "lint        - run ruff"
	@echo "report      - build the static site into _build/html"

fetch:
	python scripts/fetch_data.py

fetch-check:
	python scripts/fetch_data.py --check
```

- [ ] **Step 3: Verify against the real files**

Run: `make fetch-check`
Expected: `13/13 sources ready.` and exit code 0, since every file is already on disk.

Run: `make fetch`
Expected: every line `[OK     ]`, nothing downloaded, exit 0 (idempotence).

- [ ] **Step 4: Commit**

```bash
git add scripts/fetch_data.py Makefile
git rm --cached scripts/download_data.py 2>/dev/null || true
git commit -m "Add checksum-verified fetch CLI, retire download_data.py

make fetch downloads whatever is missing or corrupt and is idempotent:
a second run downloads nothing. make fetch-check reports status only,
which is what download_data.py used to do."
```

---

## Task 6: Publish the GitHub Release

The ICNF and INE workbooks have no scriptable origin URL, so they are mirrored as release assets.

**Files:** none in the repo — this publishes to GitHub.

- [ ] **Step 1: Confirm before publishing**

`rogerjeasy/sustainability-analytics` is **public**, so these assets become publicly downloadable. That is appropriate for published INE and ICNF government statistics, but confirm with the repo owner before running the next step if you are not them.

- [ ] **Step 2: Create the release with all seven workbooks**

```bash
gh release create v0.1-data \
  --repo rogerjeasy/sustainability-analytics \
  --title "Raw data mirror v0.1" \
  --notes "Mirror of the small raw inputs so \`make fetch\` can run unattended.

**Contents**
- \`EstatisticasIncendiosSGIF-2001-2025.xlsx\` — rural fire statistics 2001-2025, mainland Portugal.
  Source: Instituto da Conservação da Natureza e das Florestas (ICNF), https://www.icnf.pt
- \`AER2019_II_01.xlsx\` … \`AER2024_II_01.xlsx\` — Anuário Estatístico Regional, chapter II.01 (Population).
  Source: Instituto Nacional de Estatística (INE), https://www.ine.pt

Both are published official statistics, mirrored unmodified for reproducibility.
Checksums are committed in \`config/sources.yml\`; EFFIS is distributed separately
because of its size." \
  data/raw/icnf/EstatisticasIncendiosSGIF-2001-2025.xlsx \
  data/raw/ine/AER2019_II_01.xlsx \
  data/raw/ine/AER2020_II_01.xlsx \
  data/raw/ine/AER2021_II_01.xlsx \
  data/raw/ine/AER2022_II_01.xlsx \
  data/raw/ine/AER2023_II_01.xlsx \
  data/raw/ine/AER2024_II_01.xlsx
```

- [ ] **Step 3: Verify the URLs in the manifest resolve**

```bash
python -c "
from wildfires.fetch import load_manifest
for s in load_manifest():
    if s.kind == 'http' and 'releases/download' in (s.url or ''):
        print(s.url)
" | while read u; do
  printf '%-100s ' "$u"
  curl -sIL --max-time 30 -o /dev/null -w 'HTTP %{http_code}\n' "$u"
done
```

Expected: `HTTP 200` for all seven. A 404 means the asset name in the manifest does not match the uploaded filename.

- [ ] **Step 4: Prove a clean fetch works**

```bash
mv data/raw/ine/AER2019_II_01.xlsx /tmp/aer2019.backup
python scripts/fetch_data.py --only AER2019
diff data/raw/ine/AER2019_II_01.xlsx /tmp/aer2019.backup && echo "identical" && rm /tmp/aer2019.backup
```

Expected: `[FETCH ]`, then `1/1 sources ready.`, then `identical`.

- [ ] **Step 5: Commit any manifest URL corrections**

```bash
git add config/sources.yml
git commit -m "Point manifest at the v0.1-data release assets" || echo "no changes needed"
```

---

## Task 7: ICNF municipality-year stage

**Files:**
- Create: `src/wildfires/pipeline.py`
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: `wildfires.io.load_icnf`
- Produces: `build_icnf(save: bool = False) -> pd.DataFrame` with columns `dtcc`, `year`, `n_fires`, `burned_ha_total`, `burned_ha_forest`, `burned_ha_shrub`, `burned_ha_agric`, `burned_ha_total_ignited`, `burned_ha_forest_ignited`, `burned_ha_shrub_ignited`, `burned_ha_agric_ignited`, 8 × `n_fires_*ha`, 6 × `cause_*`, `n_fires_gt24h`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_pipeline.py`:

```python
"""Tests for the preprocessing stages.

Stages that need the 565 MB EFFIS files skip when those are absent; the INE and
ICNF workbooks are small enough to exercise directly.
"""

from __future__ import annotations

import pytest

from wildfires.config import PATHS

icnf_only = pytest.mark.skipif(
    not PATHS["raw"]["icnf_statistics"].exists(),
    reason="ICNF workbook not present (run make fetch)",
)


@icnf_only
class TestICNFStage:
    @pytest.fixture(scope="class")
    def icnf(self):
        from wildfires.pipeline import build_icnf

        return build_icnf()

    def test_one_row_per_municipality_year(self, icnf):
        assert not icnf.duplicated(["dtcc", "year"]).any()

    def test_spans_the_full_icnf_history(self, icnf):
        assert icnf.year.min() == 2001
        assert icnf.year.max() == 2025
        assert len(icnf) == 6921

    def test_municipality_count_grows_to_278(self, icnf):
        """270 municipalities report in 2001, 278 from 2006 on. Not a flat product."""
        per_year = icnf.groupby("year").dtcc.nunique()
        assert per_year.loc[2001] == 270
        assert per_year.loc[2019] == 278
        assert per_year.max() == 278

    def test_dtcc_is_four_characters(self, icnf):
        assert icnf.dtcc.str.len().eq(4).all()

    def test_within_municipality_area_is_absent_before_2017(self, icnf):
        """AreaArd*_NoConcelho simply does not exist before 2017 in the source."""
        early = icnf[icnf.year < 2017]
        assert early.burned_ha_total.isna().all()

    def test_within_municipality_area_is_present_from_2017(self, icnf):
        assert icnf[icnf.year == 2019].burned_ha_total.notna().all()

    def test_ignition_area_spans_every_year(self, icnf):
        """The _IncendioInicioConc convention is the only one covering 2001-2016."""
        per_year = icnf.groupby("year").burned_ha_total_ignited.notna().sum()
        assert (per_year > 0).all()

    def test_the_two_conventions_are_kept_separate(self, icnf):
        """They answer different questions and must never be coalesced."""
        both = icnf[icnf.year >= 2017]
        assert not both.burned_ha_total.equals(both.burned_ha_total_ignited)

    def test_missing_marker_never_survives_as_a_string(self, icnf):
        numeric = icnf.drop(columns=["dtcc"])
        for column in numeric.columns:
            assert numeric[column].map(lambda v: isinstance(v, str)).sum() == 0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_pipeline.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'wildfires.pipeline'`

- [ ] **Step 3: Implement the stage**

Create `src/wildfires/pipeline.py`:

```python
"""The preprocessing stages that turn data/raw into analysis-ready datasets.

Each stage writes exactly one artifact and can be run on its own, so a failure
part-way through does not discard the work already done.
"""

from __future__ import annotations

import pandas as pd

from wildfires.config import PATHS
from wildfires.io import load_icnf

# ICNF publishes two burned-area conventions that answer different questions:
#
#   _NoConcelho          area that burned WITHIN this municipality
#   _IncendioInicioConc  area of fires that IGNITED in this municipality
#
# _NoConcelho is empty before 2017. Both are carried, distinctly named; coalescing
# them would silently mix two different measures across the 2017 boundary.
ICNF_AREA_WITHIN = {
    "AreaArdTotal_NoConcelho": "burned_ha_total",
    "AreaArdPov_NoConcelho": "burned_ha_forest",
    "AreaArdMato_NoConcelho": "burned_ha_shrub",
    "AreaArdAgric_NoConcelho": "burned_ha_agric",
}
ICNF_AREA_IGNITED = {
    "AreaArdTotal_IncendioInicioConc": "burned_ha_total_ignited",
    "AreaArdPov_IncendioInicioConc": "burned_ha_forest_ignited",
    "AreaArdMato_IncendioInicioConc": "burned_ha_shrub_ignited",
    "AreaArdAgric_IncendioInicioConc": "burned_ha_agric_ignited",
}
ICNF_SIZE_CLASSES = {
    "NIncRur_0_1ha": "n_fires_0_1ha",
    "NIncRur_1_10ha": "n_fires_1_10ha",
    "NIncRur_10_20ha": "n_fires_10_20ha",
    "NIncRur_20_50ha": "n_fires_20_50ha",
    "NIncRur_50_100ha": "n_fires_50_100ha",
    "NIncRur_100_500ha": "n_fires_100_500ha",
    "NIncRur_500_1000ha": "n_fires_500_1000ha",
    "NIncRur_1000_n_ha": "n_fires_1000_plus_ha",
}
ICNF_CAUSES = {
    "NInc_Natural": "cause_natural",
    "NInc_Negligente": "cause_negligent",
    "NInc_Intencionais": "cause_intentional",
    "NInc_Reacendimentos": "cause_rekindle",
    "NInc_Desconhecida": "cause_unknown",
    "NInc_NaoInvestigados": "cause_uninvestigated",
}
ICNF_RENAMES = {
    "Num_IncendiosRurais": "n_fires",
    "Ninc_Sup24h": "n_fires_gt24h",
    **ICNF_AREA_WITHIN, **ICNF_AREA_IGNITED, **ICNF_SIZE_CLASSES, **ICNF_CAUSES,
}


def build_icnf(save: bool = False) -> pd.DataFrame:
    """ICNF rural fire statistics as one tidy row per (dtcc, year), 2001-2025."""
    df = load_icnf("concelho")
    df = df.rename(columns=ICNF_RENAMES)

    keep = ["dtcc", "year", *[c for c in ICNF_RENAMES.values() if c in df.columns]]
    out = df[keep].copy()

    for column in out.columns.drop(["dtcc", "year"]):
        out[column] = pd.to_numeric(out[column], errors="coerce")

    out = out.sort_values(["dtcc", "year"]).reset_index(drop=True)
    if save:
        target = PATHS["interim"]["icnf_municipal_year"]
        target.parent.mkdir(parents=True, exist_ok=True)
        out.to_parquet(target, index=False)
    return out
```

Add to `config/paths.yml` under `interim:`:

```yaml
  icnf_municipal_year: data/interim/icnf_municipal_year.parquet
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_pipeline.py -v`
Expected: PASS. If `test_spans_the_full_icnf_history` fails on the row count, ICNF has published a newer workbook — update the manifest checksum and the expected count together, in one commit, with the new count stated in the message.

- [ ] **Step 5: Commit**

```bash
git add src/wildfires/pipeline.py tests/test_pipeline.py config/paths.yml
git commit -m "Add ICNF municipality-year preprocessing stage

Carries both burned-area conventions under distinct names. _NoConcelho
(burned within the municipality) is empty before 2017; _IncendioInicioConc
(fires that ignited there) spans 2001-2025. They measure different things
and are never coalesced."
```

---

## Task 8: INE municipality-year stage

**Files:**
- Modify: `src/wildfires/pipeline.py`, `config/paths.yml`
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: Task 1's `load_indicators_all`, `series_breaks`; existing `ine.load_population_all`, `add_aging_measures`, `add_territory_level`
- Produces: `build_ine(save: bool = False) -> pd.DataFrame` with `dtcc`, `year`, `territory`, the six population counts, five `share_*`, `aging_index`, `old_age_dependency`, and the Task 1 indicator columns

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_pipeline.py`:

```python
ine_only = pytest.mark.skipif(
    not (PATHS["raw"]["ine_aer_dir"] / "AER2024_II_01.xlsx").exists(),
    reason="INE workbooks not present (run make fetch)",
)


@ine_only
class TestINEStage:
    @pytest.fixture(scope="class")
    def ine(self):
        from wildfires.pipeline import build_ine

        return build_ine()

    def test_one_row_per_municipality_year(self, ine):
        assert not ine.duplicated(["dtcc", "year"]).any()

    def test_covers_308_municipalities_for_six_years(self, ine):
        assert sorted(ine.year.unique()) == [2019, 2020, 2021, 2022, 2023, 2024]
        assert set(ine.groupby("year").size()) == {308}

    def test_age_shares_sum_to_one_hundred(self, ine):
        parts = (ine.share_0_14 + ine.share_15_24 + ine.share_25_64 + ine.share_65_plus)
        assert (parts - 100).abs().max() < 1e-6

    def test_share_75_plus_is_nested_inside_65_plus(self, ine):
        """75+ is a subset of 65+, not a fifth disjoint band."""
        assert (ine.share_75_plus <= ine.share_65_plus + 1e-9).all()

    def test_rate_columns_are_populated(self, ine):
        for column in ("pop_density", "birth_rate", "death_rate",
                       "growth_effective", "growth_natural", "growth_migratory"):
            assert ine[column].notna().sum() > 1000, f"{column} mostly empty"

    def test_derived_aging_index_matches_ine_published_value(self, ine):
        """Independent cross-check: our arithmetic against INE's own column."""
        both = ine[ine.aging_index.notna() & ine.aging_index_ine.notna()]
        assert len(both) > 1000
        assert (both.aging_index - both.aging_index_ine).abs().median() < 1.0

    def test_nothing_was_imputed(self, ine):
        """2021 density carries a break in series; values stay exactly as published."""
        assert ine[ine.year == 2021].pop_density.notna().sum() > 250
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_pipeline.py -k INEStage -v`
Expected: FAIL with `ImportError: cannot import name 'build_ine'`

- [ ] **Step 3: Implement the stage**

Append to `src/wildfires/pipeline.py`:

```python
from wildfires.ine import (
    add_aging_measures,
    add_territory_level,
    load_indicators_all,
    load_population_all,
    series_breaks,
)


def build_ine(save: bool = False) -> pd.DataFrame:
    """INE demography as one row per (dtcc, year) for the six AER editions.

    Age-group counts come from the II_01_03/_02 tables, the rates and density from
    II_01_01/_01c. Both are keyed on the 7-digit hierarchical code, whose last four
    characters are the dtcc.
    """
    population = add_aging_measures(add_territory_level(load_population_all()))
    population = population[population.level == "municipality"].copy()

    for band in ("0_14", "15_24", "25_64", "65_plus", "75_plus"):
        population[f"share_{band}"] = 100 * population[f"pop_{band}"] / population["pop_total"]

    indicators = load_indicators_all()
    indicators = indicators[
        indicators.code.str.len().eq(7) & indicators.code.str[3:].ne("0000")
    ].copy()

    merged = population.merge(
        indicators.drop(columns=["territory"]),
        on=["code", "year"], how="left", validate="one_to_one",
    )
    merged["dtcc"] = merged["code"].str[-4:]

    columns = [
        "dtcc", "year", "territory",
        "pop_total", "pop_0_14", "pop_15_24", "pop_25_64", "pop_65_plus", "pop_75_plus",
        "share_0_14", "share_15_24", "share_25_64", "share_65_plus", "share_75_plus",
        "aging_index", "old_age_dependency",
        "pop_density", "growth_effective", "growth_natural", "growth_migratory",
        "birth_rate", "death_rate",
        "aging_index_ine", "renewal_index", "old_age_dependency_ine", "longevity_index",
    ]
    out = merged[columns].sort_values(["dtcc", "year"]).reset_index(drop=True)

    if save:
        target = PATHS["interim"]["ine_municipal_year"]
        target.parent.mkdir(parents=True, exist_ok=True)
        out.to_parquet(target, index=False)

        breaks = PATHS["processed"]["series_breaks"]
        breaks.parent.mkdir(parents=True, exist_ok=True)
        series_breaks().to_csv(breaks, index=False)
    return out
```

Add to `config/paths.yml`:

```yaml
interim:
  ine_municipal_year: data/interim/ine_municipal_year.parquet
processed:
  series_breaks: data/processed/series_breaks.csv
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_pipeline.py -v && ruff check src tests`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/wildfires/pipeline.py tests/test_pipeline.py config/paths.yml
git commit -m "Add INE municipality-year preprocessing stage

Joins the age-group counts to the II_01_01 rate indicators on the
7-digit hierarchical code, whose last four characters are the dtcc.

The derived aging index is cross-checked against INE's own published
column, which catches a column misalignment that a self-consistent
parse would not."
```

---

## Task 9: EFFIS municipality-year stage

EFFIS is the only source with real per-fire duration (`FIREDATE` → `FINALDATE`) and per-fire land-cover composition.

**Files:**
- Modify: `src/wildfires/pipeline.py`, `config/paths.yml`
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: `wildfires.io.load_effis_polygons`, `load_municipalities`, `EFFIS_LANDCOVER_COLS`
- Produces: `effis_to_municipality(...) -> gpd.GeoDataFrame` (**moved here from `merge.py`**), `add_fire_duration(df) -> pd.DataFrame`, `build_effis(save: bool = False) -> pd.DataFrame`

**Import direction (do not reverse):** `merge.py` imports from `pipeline.py`, never the
other way. `effis_to_municipality` moves out of `merge.py` into `pipeline.py` in this
task precisely to keep that one-directional; leaving it in `merge.py` creates a circular
import as soon as Task 10 has `merge.py` import the stages. with `dtcc`, `year`, `effis_n_fires`, `effis_burnt_ha_total`, `effis_burnt_ha_median`, `effis_burnt_ha_max`, `effis_duration_days_mean`, `effis_duration_days_max`, 9 × `lc_*_mean`, `percna2k_mean`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_pipeline.py`:

```python
effis_only = pytest.mark.skipif(
    not PATHS["interim"]["effis_subset_geo"].exists(),
    reason="EFFIS geodata not present (run make fetch; ~565 MB)",
)


class TestEffisDuration:
    """Duration arithmetic, exercised on a fixture so it needs no 565 MB download."""

    def test_duration_is_days_between_first_and_final_date(self):
        import pandas as pd

        from wildfires.pipeline import add_fire_duration

        df = pd.DataFrame({
            "FIREDATE": pd.to_datetime(["2019-07-01T00:00:00", "2019-08-10T12:00:00"]),
            "FINALDATE": pd.to_datetime(["2019-07-04T00:00:00", "2019-08-11T00:00:00"]),
        })
        out = add_fire_duration(df)
        assert out.duration_days.tolist() == [3.0, 0.5]

    def test_missing_final_date_yields_na_not_zero(self):
        """An unclosed fire is unknown duration, not a zero-day fire."""
        import pandas as pd

        from wildfires.pipeline import add_fire_duration

        df = pd.DataFrame({
            "FIREDATE": pd.to_datetime(["2019-07-01"]),
            "FINALDATE": [pd.NaT],
        })
        assert add_fire_duration(df).duration_days.isna().all()


@effis_only
class TestEffisStage:
    @pytest.fixture(scope="class")
    def effis(self):
        from wildfires.pipeline import build_effis

        return build_effis()

    def test_one_row_per_municipality_year(self, effis):
        assert not effis.duplicated(["dtcc", "year"]).any()

    def test_dtcc_is_four_characters(self, effis):
        assert effis.dtcc.str.len().eq(4).all()

    def test_land_cover_means_are_percentages(self, effis):
        for column in [c for c in effis.columns if c.startswith("lc_")]:
            values = effis[column].dropna()
            assert values.between(0, 100).all(), f"{column} outside 0-100"

    def test_duration_is_never_negative(self, effis):
        assert (effis.effis_duration_days_max.dropna() >= 0).all()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_pipeline.py -k Effis -v`
Expected: FAIL with `ImportError: cannot import name 'add_fire_duration'`

- [ ] **Step 3: Implement the stage**

Append to `src/wildfires/pipeline.py`:

First **move** `effis_to_municipality` out of `src/wildfires/merge.py` and into
`src/wildfires/pipeline.py` unchanged (it is a preprocessing step, not an assembly step),
then delete `aggregate_fires` from `merge.py` — `build_effis` supersedes it. Update the
imports at the top of `merge.py` accordingly.

```python
import geopandas as gpd

from wildfires.config import CRS_METRIC
from wildfires.io import EFFIS_LANDCOVER_COLS, load_effis_polygons, load_municipalities


def effis_to_municipality(
    fires: gpd.GeoDataFrame | None = None,
    municipalities: gpd.GeoDataFrame | None = None,
) -> gpd.GeoDataFrame:
    """Assign each EFFIS burn polygon to a municipality by spatial join.

    EFFIS's COMMUNE field is the freguesia (civil parish), one level finer than the
    concelho, and is free text with no code, so it cannot be joined to ICNF or INE
    directly. The polygon representative point is used; a fire crossing a municipal
    border is attributed to one municipality, a known and documented simplification.
    """
    fires = load_effis_polygons() if fires is None else fires
    municipalities = load_municipalities() if municipalities is None else municipalities

    # Representative points must be computed in a projected CRS to be valid.
    pts = fires.to_crs(CRS_METRIC).copy()
    pts["geometry"] = pts.geometry.representative_point()

    joined = gpd.sjoin(
        pts,
        municipalities.to_crs(CRS_METRIC)[["dtcc", "municipality", "district", "geometry"]],
        how="left",
        predicate="within",
    ).drop(columns="index_right")
    return joined


def add_fire_duration(df: pd.DataFrame) -> pd.DataFrame:
    """Days between FIREDATE and FINALDATE.

    A fire with no FINALDATE has unknown duration, which stays NaN. Filling it
    with zero would report the longest-burning fires as the shortest.
    """
    out = df.copy()
    out["duration_days"] = (
        pd.to_datetime(out["FINALDATE"], errors="coerce")
        - pd.to_datetime(out["FIREDATE"], errors="coerce")
    ).dt.total_seconds() / 86400
    return out


def build_effis(save: bool = False) -> pd.DataFrame:
    """EFFIS burn perimeters aggregated to one row per (dtcc, year)."""
    fires = add_fire_duration(effis_to_municipality())
    fires = fires[fires["dtcc"].notna()].copy()
    if "fire_year" not in fires.columns:
        fires["fire_year"] = pd.to_datetime(
            fires["FIREDATE"], format="ISO8601", errors="coerce"
        ).dt.year

    grouped = fires.groupby(["dtcc", "fire_year"])
    size = grouped["AREA_HA"].agg(
        effis_n_fires="count",
        effis_burnt_ha_total="sum",
        effis_burnt_ha_median="median",
        effis_burnt_ha_max="max",
    )
    duration = grouped["duration_days"].agg(
        effis_duration_days_mean="mean",
        effis_duration_days_max="max",
    )
    composition = grouped[[*EFFIS_LANDCOVER_COLS, "PERCNA2K"]].mean()
    composition.columns = [f"lc_{c.lower()}_mean" for c in EFFIS_LANDCOVER_COLS] + \
                          ["percna2k_mean"]

    out = (
        size.join(duration).join(composition)
        .reset_index().rename(columns={"fire_year": "year"})
    )
    out["year"] = out["year"].astype("Int64")
    out = out.sort_values(["dtcc", "year"]).reset_index(drop=True)

    if save:
        target = PATHS["interim"]["effis_municipal_year"]
        target.parent.mkdir(parents=True, exist_ok=True)
        out.to_parquet(target, index=False)
    return out
```

Add to `config/paths.yml` under `interim:`:

```yaml
  effis_municipal_year: data/interim/effis_municipal_year.parquet
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_pipeline.py -v`
Expected: PASS. The `TestEffisStage` class skips if EFFIS is absent; `TestEffisDuration` must run either way.

- [ ] **Step 5: Commit**

```bash
git add src/wildfires/pipeline.py src/wildfires/merge.py tests/test_pipeline.py config/paths.yml
git commit -m "Add EFFIS municipality-year preprocessing stage

Moves effis_to_municipality out of merge.py so imports flow one way,
merge.py -> pipeline.py, instead of forming a cycle.

EFFIS is the only source with real per-fire duration and per-fire land
cover composition. A fire with no FINALDATE keeps NaN duration: filling
it with zero would report the longest-burning fires as the shortest."
```

---

## Task 10: Panel assembly

**Files:**
- Modify: `src/wildfires/merge.py`, `config/paths.yml`
- Test: `tests/test_merge.py`

**Interfaces:**
- Consumes: Tasks 7–9's `build_icnf`, `build_ine`, `build_effis`; `io.load_municipalities`; `ine.load_typology_all`
- `merge.py` must no longer define `effis_to_municipality` or `aggregate_fires` — Task 9
  moved the first into `pipeline.py` and superseded the second. Imports flow one way:
  `merge.py` → `pipeline.py`.
- Produces:
  - `municipality_areas() -> pd.DataFrame` — `dtcc`, `municipality_area_km2`
  - `build_fire_panel(save: bool = False) -> pd.DataFrame` — ICNF + EFFIS, 2001–2025
  - `build_panel(save: bool = False) -> pd.DataFrame` — fire + demography, 2019–2024
  - `build_typology(save: bool = False) -> pd.DataFrame` — NUTS III × APU/AMU/APR

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_merge.py`:

```python
from wildfires.config import PATHS

full_data = pytest.mark.skipif(
    not PATHS["raw"]["icnf_statistics"].exists()
    or not (PATHS["raw"]["ine_aer_dir"] / "AER2024_II_01.xlsx").exists(),
    reason="raw workbooks not present (run make fetch)",
)


@full_data
class TestPanels:
    @pytest.fixture(scope="class")
    def panel(self):
        from wildfires.merge import build_panel

        return build_panel()

    @pytest.fixture(scope="class")
    def fire_panel(self):
        from wildfires.merge import build_fire_panel

        return build_fire_panel()

    def test_panel_is_278_municipalities_by_six_years(self, panel):
        assert len(panel) == 1668
        assert panel.dtcc.nunique() == 278
        assert sorted(panel.year.unique()) == [2019, 2020, 2021, 2022, 2023, 2024]

    def test_panel_key_is_unique(self, panel):
        assert not panel.duplicated(["dtcc", "year"]).any()

    def test_join_lost_no_municipality(self, panel):
        """INE, ICNF and GADM overlap on exactly 278 mainland municipalities."""
        assert set(panel.groupby("year").size()) == {278}

    def test_demography_is_attached_everywhere(self, panel):
        for column in ("pop_total", "share_65_plus", "birth_rate", "pop_density"):
            assert panel[column].notna().sum() > 1500, f"{column} mostly unattached"

    def test_fire_columns_are_attached(self, panel):
        assert panel.n_fires.notna().all()

    def test_burn_rate_is_a_fraction(self, panel):
        rate = panel.burn_rate.dropna()
        assert (rate >= 0).all()
        assert (rate <= 1.5).all(), "burn_rate far above 1 means an area-unit mismatch"

    def test_fire_panel_spans_the_full_history(self, fire_panel):
        assert fire_panel.year.min() == 2001
        assert fire_panel.year.max() == 2025

    def test_fire_panel_carries_no_demography(self, fire_panel):
        """It must not inherit the 2019-2024 INE ceiling."""
        assert "pop_total" not in fire_panel.columns
        assert "birth_rate" not in fire_panel.columns

    def test_no_merge_multiplied_rows(self, fire_panel):
        assert not fire_panel.duplicated(["dtcc", "year"]).any()


@full_data
class TestMunicipalityAreas:
    def test_areas_are_plausible_for_portugal(self):
        from wildfires.merge import municipality_areas

        areas = municipality_areas()
        # Portugal's smallest concelho is São João da Madeira at ~8 km2; the
        # largest is Odemira at ~1720 km2.
        assert areas.municipality_area_km2.min() > 5
        assert areas.municipality_area_km2.max() < 2000
        assert len(areas) >= 278


@full_data
class TestTypologyTable:
    def test_is_nuts3_level_and_never_joined_to_municipalities(self):
        """II_01_04/_05 carry no municipality code; they stay a separate table."""
        from wildfires.merge import build_typology

        typology = build_typology()
        assert "dtcc" not in typology.columns
        assert set(typology.typology) == {"APU", "AMU", "APR"}

    def test_2022_gap_is_preserved(self):
        from wildfires.merge import build_typology

        assert 2022 not in set(build_typology().year)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_merge.py -k "Panels or Municipality or Typology" -v`
Expected: FAIL with `ImportError: cannot import name 'build_fire_panel'`

- [ ] **Step 3: Implement the assembly**

Replace `build_panel` in `src/wildfires/merge.py` and add the new functions:

```python
from wildfires.config import CRS_METRIC, PATHS
from wildfires.ine import load_typology_all
from wildfires.io import load_municipalities
from wildfires.pipeline import build_effis, build_icnf, build_ine


def municipality_areas() -> pd.DataFrame:
    """Municipality area in km2, computed from GADM geometry in a metric CRS.

    Replaces the data.gov.pt dimensions table, which is not distributed with this
    project. EPSG:3763 (PT-TM06/ETRS89) is the projection areas must be measured in;
    computing area in EPSG:4326 would return square degrees.
    """
    gdf = load_municipalities(mainland_only=True).to_crs(CRS_METRIC)
    return pd.DataFrame({
        "dtcc": gdf["dtcc"].astype("string"),
        "municipality_area_km2": gdf.geometry.area / 1e6,
    }).dropna(subset=["dtcc"]).reset_index(drop=True)


def build_fire_panel(save: bool = False) -> pd.DataFrame:
    """ICNF + EFFIS, 2001-2025. Carries no demography, so no 2019-2024 ceiling."""
    icnf = build_icnf()
    effis = build_effis()

    panel = icnf.merge(effis, on=["dtcc", "year"], how="left", validate="one_to_one")
    panel = panel.merge(municipality_areas(), on="dtcc", how="left", validate="many_to_one")

    hectares = panel["municipality_area_km2"] * 100
    panel["burn_rate"] = panel["burned_ha_total"] / hectares
    panel["burn_rate_ignited"] = panel["burned_ha_total_ignited"] / hectares

    panel = panel.sort_values(["dtcc", "year"]).reset_index(drop=True)
    if save:
        target = PATHS["processed"]["fire_panel"]
        target.parent.mkdir(parents=True, exist_ok=True)
        panel.to_parquet(target, index=False)
    return panel


def build_panel(save: bool = False) -> pd.DataFrame:
    """The analysis panel: fire + demography, one row per (dtcc, year), 2019-2024.

    The inner join on INE is deliberate. INE AER exists only for 2019-2024 and
    covers 308 municipalities; ICNF covers 278 mainland ones. The 278 that appear
    in both are the analysis population, and every one of them matches.
    """
    fire = build_fire_panel()
    demography = build_ine()

    panel = fire.merge(demography, on=["dtcc", "year"], how="inner", validate="one_to_one")
    panel = panel.sort_values(["dtcc", "year"]).reset_index(drop=True)

    if save:
        target = PATHS["processed"]["panel"]
        target.parent.mkdir(parents=True, exist_ok=True)
        panel.to_parquet(target, index=False)
    return panel


def build_typology(save: bool = False) -> pd.DataFrame:
    """INE tables II.1.4/II.1.5: population by urban typology, at NUTS III.

    Kept deliberately separate: these tables carry no municipality code, so they
    cannot join to the panel. AER2022 does not publish them, and that gap stays a
    gap rather than being filled from a neighbouring year.
    """
    typology = load_typology_all()
    if save:
        target = PATHS["processed"]["typology_nuts3"]
        target.parent.mkdir(parents=True, exist_ok=True)
        typology.to_parquet(target, index=False)
    return typology
```

Add to `config/paths.yml` under `processed:`:

```yaml
  fire_panel:      data/processed/fire_panel_municipality_year.parquet
  typology_nuts3:  data/processed/ine_typology_nuts3.parquet
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_merge.py -v`
Expected: PASS, in particular `test_panel_is_278_municipalities_by_six_years` at exactly 1668 rows.

If `test_burn_rate_is_a_fraction` fails, the area units are mismatched: `municipality_area_km2 * 100` converts km² to hectares, matching ICNF's hectare areas.

- [ ] **Step 5: Commit**

```bash
git add src/wildfires/merge.py tests/test_merge.py config/paths.yml
git commit -m "Assemble the analysis and fire panels

build_panel completes the INE attachment that was left as a TODO: 278
mainland municipalities x 2019-2024 = 1668 rows, no key loss.

build_fire_panel carries ICNF + EFFIS across 2001-2025 with no
demography, so the 18 years of fire history predating INE AER stay
usable by the time-series chapter.

Municipality area is computed from GADM geometry in EPSG:3763."
```

---

## Task 11: Validation stage

**Files:**
- Create: `src/wildfires/validate.py`
- Test: `tests/test_validate.py`

**Interfaces:**
- Produces:
  - `Check` dataclass: `name: str`, `passed: bool`, `detail: str`
  - `validate_panel(panel: pd.DataFrame) -> list[Check]`
  - `validate_fire_panel(panel: pd.DataFrame) -> list[Check]`
  - `render_report(results: dict[str, list[Check]]) -> str`
  - `null_rate_table(panel) -> pd.DataFrame`, `render_null_rates(panel) -> str`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_validate.py`:

```python
"""Tests for the panel contract checks. These run on fixtures, never on real data."""

from __future__ import annotations

import pandas as pd

from wildfires.validate import Check, render_report, validate_panel


def _panel(rows=1668, municipalities=278):
    years = [2019, 2020, 2021, 2022, 2023, 2024]
    dtccs = [f"{i:04d}" for i in range(1, municipalities + 1)]
    frame = pd.DataFrame(
        [(d, y) for d in dtccs for y in years], columns=["dtcc", "year"]
    ).head(rows)
    frame["n_fires"] = 1.0
    frame["pop_total"] = 1000.0
    return frame


class TestValidatePanel:
    def test_clean_panel_passes_everything(self):
        assert all(c.passed for c in validate_panel(_panel()))

    def test_duplicate_key_is_caught(self):
        frame = pd.concat([_panel(), _panel().head(1)], ignore_index=True)
        failures = [c for c in validate_panel(frame) if not c.passed]
        assert any("unique" in c.name for c in failures)

    def test_wrong_row_count_is_caught(self):
        failures = [c for c in validate_panel(_panel(rows=1000)) if not c.passed]
        assert any("row count" in c.name for c in failures)

    def test_all_null_column_is_caught(self):
        """An entirely empty column means a rename or join silently failed."""
        frame = _panel()
        frame["birth_rate"] = pd.NA
        failures = [c for c in validate_panel(frame) if not c.passed]
        assert any("all-null" in c.name for c in failures)


class TestRenderReport:
    def test_report_names_the_failing_check(self):
        results = {"panel": [Check(name="row count", passed=False, detail="got 3")]}
        text = render_report(results)
        assert "row count" in text
        assert "got 3" in text
        assert "FAIL" in text

    def test_report_marks_a_clean_run(self):
        results = {"panel": [Check(name="row count", passed=True, detail="1668")]}
        assert "PASS" in render_report(results)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_validate.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'wildfires.validate'`

- [ ] **Step 3: Implement validation**

Create `src/wildfires/validate.py`:

```python
"""Contract checks the panels must satisfy before anyone analyses them.

The point is to fail loudly. A panel with a silently empty column or a merge that
multiplied rows produces confident, wrong answers downstream.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

EXPECTED_PANEL_ROWS = 1668
EXPECTED_MUNICIPALITIES = 278
EXPECTED_PANEL_YEARS = [2019, 2020, 2021, 2022, 2023, 2024]

# Columns allowed to be entirely null in the fire panel, with the documented reason.
KNOWN_SPARSE = {
    "burned_ha_total": "ICNF publishes _NoConcelho only from 2017",
    "burned_ha_forest": "ICNF publishes _NoConcelho only from 2017",
    "burned_ha_shrub": "ICNF publishes _NoConcelho only from 2017",
    "burned_ha_agric": "ICNF publishes _NoConcelho only from 2017",
    "burn_rate": "derived from _NoConcelho, so also 2017+",
}


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    detail: str


def _key_checks(panel: pd.DataFrame) -> list[Check]:
    duplicated = int(panel.duplicated(["dtcc", "year"]).sum())
    return [Check(
        name="(dtcc, year) is unique",
        passed=duplicated == 0,
        detail=f"{duplicated} duplicate keys",
    )]


def _null_checks(panel: pd.DataFrame, allowed: dict[str, str]) -> list[Check]:
    empty = [c for c in panel.columns if panel[c].isna().all() and c not in allowed]
    return [Check(
        name="no all-null column",
        passed=not empty,
        detail="none" if not empty else f"empty: {', '.join(empty)}",
    )]


def validate_panel(panel: pd.DataFrame) -> list[Check]:
    """Contract for the 2019-2024 joined panel."""
    checks = _key_checks(panel)
    checks.append(Check(
        name="row count is 1668",
        passed=len(panel) == EXPECTED_PANEL_ROWS,
        detail=f"{len(panel)} rows (expected {EXPECTED_PANEL_ROWS})",
    ))
    checks.append(Check(
        name="278 municipalities",
        passed=panel.dtcc.nunique() == EXPECTED_MUNICIPALITIES,
        detail=f"{panel.dtcc.nunique()} distinct dtcc",
    ))
    checks.append(Check(
        name="years are 2019-2024",
        passed=sorted(panel.year.unique()) == EXPECTED_PANEL_YEARS,
        detail=f"{sorted(panel.year.unique())}",
    ))
    checks.extend(_null_checks(panel, allowed={}))
    return checks


def validate_fire_panel(panel: pd.DataFrame) -> list[Check]:
    """Contract for the 2001-2025 fire panel."""
    checks = _key_checks(panel)
    checks.append(Check(
        name="spans 2001-2025",
        passed=panel.year.min() == 2001 and panel.year.max() == 2025,
        detail=f"{panel.year.min()}-{panel.year.max()}",
    ))
    checks.append(Check(
        name="carries no demography",
        passed="pop_total" not in panel.columns,
        detail="clean" if "pop_total" not in panel.columns else "pop_total leaked in",
    ))
    checks.extend(_null_checks(panel, allowed=KNOWN_SPARSE))
    return checks


def render_report(results: dict[str, list[Check]]) -> str:
    """Render the checks as Markdown for data/processed/validation_report.md."""
    lines = [
        "# Panel validation report",
        "",
        f"Generated {date.today().isoformat()}.",
        "",
    ]
    for dataset, checks in results.items():
        failed = sum(not c.passed for c in checks)
        lines += [f"## {dataset}", "",
                  f"{len(checks) - failed}/{len(checks)} checks passed.", "",
                  "| Check | Result | Detail |", "|---|---|---|"]
        for check in checks:
            lines.append(
                f"| {check.name} | {'PASS' if check.passed else 'FAIL'} | {check.detail} |"
            )
        lines.append("")

    if KNOWN_SPARSE:
        lines += ["## Known and expected gaps", ""]
        for column, reason in KNOWN_SPARSE.items():
            lines.append(f"- `{column}` — {reason}")
        lines += ["", "- `pop_density` — INE flags a break in series at 2021 "
                  "(Censos 2021 re-basing). Values are as published; see "
                  "`data/processed/series_breaks.csv`.", ""]
    return "\n".join(lines)


def null_rate_table(panel: pd.DataFrame) -> pd.DataFrame:
    """Per-column null rate, for the report's appendix."""
    return (
        panel.isna().mean().mul(100).round(2)
        .rename("null_pct").reset_index().rename(columns={"index": "column"})
        .sort_values("null_pct", ascending=False).reset_index(drop=True)
    )


def render_null_rates(panel: pd.DataFrame) -> str:
    """Markdown for the null-rate appendix.

    Written by hand rather than via DataFrame.to_markdown, which needs `tabulate` —
    a dependency this project does not carry and does not need for one table.
    """
    table = null_rate_table(panel)
    lines = ["| Column | Null % |", "|---|---|"]
    lines += [f"| `{row.column}` | {row.null_pct:.2f} |" for row in table.itertuples()]
    return "\n".join(lines)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_validate.py -v && ruff check src tests`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/wildfires/validate.py tests/test_validate.py
git commit -m "Add panel contract validation

Catches the failures that produce confident wrong answers rather than
crashes: a merge that multiplied rows, a rename that silently emptied a
column, a join that dropped municipalities.

Gaps that are real properties of the sources -- ICNF _NoConcelho before
2017, the 2021 density break -- are listed as expected rather than
flagged, so a genuine regression stands out."
```

---

## Task 12: build CLI and Makefile target

**Files:**
- Create: `scripts/build_data.py`
- Modify: `Makefile`

**Interfaces:**
- Consumes: every stage from Tasks 7–11

- [ ] **Step 1: Write the CLI**

Create `scripts/build_data.py`:

```python
#!/usr/bin/env python
"""Build every interim and processed dataset from data/raw.

    make data                 run all stages, then validate
    python scripts/build_data.py --stage ine     run one stage

Stages are ordered and each writes exactly one artifact, so a failure part-way
through does not discard completed work.
"""

from __future__ import annotations

import argparse
import sys

import pandas as pd

from wildfires.config import PATHS, project_root
from wildfires.merge import build_fire_panel, build_panel, build_typology
from wildfires.pipeline import build_effis, build_icnf, build_ine
from wildfires.validate import (
    render_null_rates,
    render_report,
    validate_fire_panel,
    validate_panel,
)

STAGES = {
    "icnf": build_icnf,
    "ine": build_ine,
    "effis": build_effis,
    "fire_panel": build_fire_panel,
    "panel": build_panel,
    "typology": build_typology,
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=sorted(STAGES),
                        help="run a single stage instead of all of them")
    parser.add_argument("--skip-validate", action="store_true",
                        help="skip the contract checks (not recommended)")
    args = parser.parse_args()

    root = project_root()
    names = [args.stage] if args.stage else list(STAGES)

    for name in names:
        print(f"[BUILD  ] {name}")
        frame = STAGES[name](save=True)
        print(f"           {len(frame):,} rows x {len(frame.columns)} columns")

    if args.stage or args.skip_validate:
        return 0

    missing = [n for n in ("panel", "fire_panel")
               if not PATHS["processed"][n].exists()]
    if missing:
        print(f"Cannot validate: {missing} were not written.")
        return 1

    # Validate the artifacts that were just written rather than rebuilding them.
    # Re-calling build_panel() here would repeat the EFFIS spatial join, the most
    # expensive step in the pipeline, two more times.
    print("\n[VALIDATE]")
    panel = pd.read_parquet(PATHS["processed"]["panel"])
    fire_panel = pd.read_parquet(PATHS["processed"]["fire_panel"])
    results = {
        "panel_municipality_year": validate_panel(panel),
        "fire_panel_municipality_year": validate_fire_panel(fire_panel),
    }
    report = render_report(results)

    appendix = ["## Null rates — panel", "", render_null_rates(panel)]
    target = PATHS["processed"]["validation_report"]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(report + "\n" + "\n".join(appendix) + "\n", encoding="utf-8")
    print(f"           wrote {target.relative_to(root)}")

    failed = [c for checks in results.values() for c in checks if not c.passed]
    for check in failed:
        print(f"           FAIL {check.name}: {check.detail}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
```

Add to `config/paths.yml` under `processed:`:

```yaml
  validation_report: data/processed/validation_report.md
```

- [ ] **Step 2: Wire up the Makefile**

Replace the `data` and `panel` targets:

```makefile
data:
	python scripts/build_data.py

panel: data
```

- [ ] **Step 3: Run the whole pipeline**

Run: `make data`
Expected: six `[BUILD ]` lines, then `[VALIDATE]` with every check `PASS`, exit 0, and these files present:

```bash
ls -la data/interim/*.parquet data/processed/
```

Expected: `icnf_municipal_year.parquet`, `ine_municipal_year.parquet`, `effis_municipal_year.parquet`, `panel_municipality_year.parquet`, `fire_panel_municipality_year.parquet`, `ine_typology_nuts3.parquet`, `series_breaks.csv`, `validation_report.md`.

- [ ] **Step 4: Confirm the panel matches the contract**

```bash
python -c "
from wildfires.io import load_panel
p = load_panel()
print(p.shape)
print(sorted(p.year.unique()))
print(p.dtcc.nunique(), 'municipalities')
"
```

Expected: `(1668, N)`, `[2019, 2020, 2021, 2022, 2023, 2024]`, `278 municipalities`.

- [ ] **Step 5: Commit**

```bash
git add scripts/build_data.py Makefile config/paths.yml
git commit -m "Add build CLI running every stage plus validation

make data builds the interim datasets, both panels and the typology
table, then writes validation_report.md and exits non-zero if any
contract check fails."
```

---

## Task 13: Documentation

**Files:**
- Modify: `README.md`, `data/README.md`, `docs/data_dictionary.md`

- [ ] **Step 1: Add a "Getting the data" section to README.md**

Insert after the project intro:

````markdown
## Getting the data

Raw inputs are ~565 MB and are not in git. Two commands take a fresh clone to an
analysis-ready panel:

```bash
make fetch    # download every raw input, checksum-verified (~565 MB, 5-15 min)
make data     # build the interim datasets and both panels (~3-5 min)
```

`make fetch` is idempotent — a second run downloads nothing. To see what is
present without downloading:

```bash
make fetch-check
```

### What you get

| File | Rows | Contents |
|---|---|---|
| `data/processed/panel_municipality_year.parquet` | 1,668 | fire + demography, 278 mainland municipalities × 2019–2024 |
| `data/processed/fire_panel_municipality_year.parquet` | 6,921 | fire only, 2001–2025 (no INE ceiling) |
| `data/processed/ine_typology_nuts3.parquet` | — | population by urban typology, NUTS III level |
| `data/processed/series_breaks.csv` | — | indicators INE flags with a break in series |
| `data/processed/validation_report.md` | — | contract checks and per-column null rates |

Read the panel with `from wildfires.io import load_panel`.

### Where the data comes from

| Source | Route |
|---|---|
| ICNF fire statistics, INE yearbooks | GitHub Release `v0.1-data` on this repo |
| EFFIS burnt-area polygons + severity raster | public Google Drive folder |
| GADM municipal boundaries | `geodata.ucdavis.edu` |

All of it is declared in `config/sources.yml`, which is the only place a URL or
checksum appears.

### When a checksum fails

`make fetch` verifies every download against a committed sha256 and discards
anything that does not match, so a truncated file can never reach the pipeline.
If a source fails repeatedly, the upstream copy has changed: confirm the new file
is the one you want, then update its `sha256` and `bytes` in `config/sources.yml`
in a commit that says what changed and why.

### Weather

Not yet acquired. Temperature, precipitation and wind are absent from the panel;
no placeholder columns are emitted. See `data/README.md` for the intended source.
````

- [ ] **Step 2: Update `data/README.md`**

- Replace the `make data` reference in the intro with `make fetch` / `make fetch-check`.
- Under `raw/effis/`, note the Google Drive mirror.
- Under `raw/icnf/` and `raw/ine/`, note the `v0.1-data` release mirror.
- Delete the `raw/eurostat/` optional section only if unused; leave the `raw/weather/` section, updating it to say weather is deliberately deferred rather than pending.
- Add, under `raw/ine/`:

```markdown
- **Sheets `II_01_01` + `II_01_01c`:** population density, effective/natural/migratory
  growth, crude birth and death rates, and the aging indices — município level. These
  are the source of every demographic rate in the panel.
- **Sheets `II_01_04`/`II_01_05`:** population by urban typology (APU/AMU/APR) — **NUTS III
  level, with no municipality code**. They cannot join to the panel and are written to
  `data/processed/ine_typology_nuts3.parquet` instead. AER2022 does not publish them.
- **Conventional signs:** `x`, `…`, `§`, `ə`, `//` mark missing or unreliable values and
  become `NaN`. `┴` marks a break in series and is recorded in
  `data/processed/series_breaks.csv` — INE flags one on population density in 2021
  (Censos 2021 re-basing), so density is not strictly comparable across 2020 → 2021.
```

- [ ] **Step 3: Write the column contract into `docs/data_dictionary.md`**

Add a section listing every panel column with its unit, source sheet and caveat, covering the table in section 4 of the spec. Include these caveats explicitly:

```markdown
### Caveats that change interpretation

- **`burned_ha_*` vs `burned_ha_*_ignited`.** The first is area burned *within* the
  municipality (ICNF `_NoConcelho`, **2017 onward only**); the second is the area of
  fires that *ignited* there (`_IncendioInicioConc`, 2001–2025). They answer different
  questions and are never combined. Any trend crossing 2017 must use the `_ignited`
  columns.
- **`n_fires_gt24h` is a count, not a duration.** It is the number of fires that burned
  longer than 24 h. Real per-fire duration is `effis_duration_days_*`, and exists only
  from 2016 (EFFIS coverage).
- **`pop_density` has a break in series at 2021.** INE flags it; values are as published
  and are not adjusted.
- **`lc_*_mean` describes what burned, not the municipality.** These are the mean
  land-cover composition of EFFIS burn perimeters. Municipality land cover as a
  predictor would need CORINE/COS, which this project does not hold.
- **EFFIS lowered its minimum mapped fire size around 2020.** Apply
  `wildfires.clean.apply_size_floor` before reading any cross-year EFFIS trend.
```

- [ ] **Step 4: Verify the documented commands actually work**

Run each command quoted in the README exactly as written:

```bash
make fetch-check && make data && python -c "from wildfires.io import load_panel; print(load_panel().shape)"
```

Expected: `13/13 sources ready.`, all checks `PASS`, `(1668, N)`.

- [ ] **Step 5: Commit**

```bash
git add README.md data/README.md docs/data_dictionary.md
git commit -m "Document the data pipeline

README gains a Getting the data section: the two commands, what each
produces, and what to do when a checksum fails. The data dictionary
records the caveats that change interpretation -- the two burned-area
conventions and their 2017 boundary, gt24h being a count rather than a
duration, the 2021 density break, and land cover describing what burned
rather than the municipality."
```

---

## Final verification

- [ ] `make lint` passes
- [ ] `make test` passes
- [ ] `make fetch-check` reports 13/13
- [ ] `make data` exits 0 with every validation check PASS
- [ ] `data/processed/validation_report.md` shows 1,668 panel rows and 278 municipalities
- [ ] `git status` is clean apart from gitignored data
- [ ] A teammate can run `git clone && make setup && make fetch && make data` — walk it once in a scratch clone to confirm nothing depends on files only present on your machine
