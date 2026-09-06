# Data acquisition & preprocessing pipeline — design

**Date:** 2026-09-06
**Status:** approved, pending implementation plan
**Scope:** the data cleaning / EDA phase — everything between "clone the repo" and
"a panel the statistics and ML chapters can read".

## 1. Problem

Raw inputs total ~565 MB and are gitignored, so a teammate who clones the repo has
no data. Acquisition is currently a README prose instruction and a script that only
*reports* what is missing. Preprocessing is spread across notebooks and two
overlapping `src/` modules, and `merge.build_panel` still carries a `TODO` where INE
demography should attach.

Goal: two commands that take a fresh clone to an analysis-ready panel, plus a column
contract the statistics and ML chapters can rely on.

## 2. Findings from the actual data

Everything in this section was read off the files, not assumed. It is recorded here
because most of the design follows from it.

### 2.1 INE sheet inventory

The requested sheets all exist, but they are not all at the same geography.

| Sheet | Table | Level | Use |
|---|---|---|---|
| `II_01_03`/`_03c` (2019–21), `II_01_02`/`_02c` (2022), `II_01_03` (2023–24) | Resident population by age group and sex | **municipality** | population, age-group shares |
| `II_01_01` + `II_01_01c` (all years) | Population indicators | **municipality** | density, growth, birth/death rates, aging indices |
| `II_01 04`/`II_01_04` | Population indicators by sex × urban typology | **NUTS III** (45–49 rows) | side table only |
| `II_01 05`/`II_01_05` | Population indicators by age group × urban typology | **NUTS III** | side table only |

`II_01_04`/`_05` carry no municipality code at all — their territorial block stops at
NUTS III. They cannot join to a municipality panel and are therefore extracted to a
separate documented table, never merged into one.

`II_01_01`/`_01c` were **not** in the original request but are the only municipality-level
source for population density, effective/natural/migratory growth rates, and crude
birth and death rates — all named as required features. They are added.

### 2.2 Layout drift across editions

| Edition | Header start | Territorial key | Age groups |
|---|---|---|---|
| 2019 | row 1 | `DTMN` + `NUTS_DTMN` | split main + `c` |
| 2020–2021 | row 1 | `NUTS_2013` + name columns | split main + `c` |
| 2022 | row 2 | `NUTS_DTMN` + name columns | split (`II_01_02`/`_02c`) |
| 2023–2024 | row 2 | `NUTS_2024` + `x` level markers | single sheet |

Sheet names are inconsistent (`II_01 04`, `II_01_04 `, `II_01_04` — space vs underscore,
some with trailing whitespace) and must be matched tolerantly.

The stable key across all six editions is the **7-digit hierarchical code**: `1111601`
is Arcos de Valdevez in both the 2019 and 2023 editions. Municipality rows are those
whose 7-digit code does not end in `0000`; `dtcc = code[-4:]`.

### 2.3 Conventional signs and break in series

`Sinais_Signs` in each workbook defines the missing-value markers: `x` (not available),
`…` (confidential), `§` (extremely unreliable), `ə` (less than half unit), `//` (not
applicable), `┴` (**break in series**).

These appear appended to *header* cells, not only to values. The 2021 header cell reads
`'Densidade populacional \n┴'`, which is why the current exact-string loader silently
drops `pop_density` for 2021 alone.

Break-in-series flags found across all six workbooks:

| Edition | Sheet | Indicator |
|---|---|---|
| 2021 | `II_01_01` | Densidade populacional |
| 2022 | `II_01_01c` | Esperança de vida à nascença |
| 2022 | `II_01_01c` | Esperança de vida aos 65 anos |

Only the first affects a panel column. `pop_density` is not strictly comparable across
2020→2021 (Censos 2021 re-basing). The flag is carried as metadata; values are used
exactly as published and are never interpolated or smoothed.

### 2.4 ICNF

`Estatisticas_Concelho` covers 2001–2025, 278 mainland municipalities (districts 01–18),
6,921 rows. Missing values are the literal string `(sem informação)`.

Two burned-area conventions that answer different questions:

- `AreaArd*_NoConcelho` — area burned **within** the municipality. **Empty before 2017.**
- `AreaArd*_IncendioInicioConc` — area of fires that **ignited** in the municipality.
  Populated for all years 2001–2025.

Both are kept, distinctly named. They are not interchangeable and must not be coalesced.

`Ninc_Sup24h` is a **count of fires burning over 24 h**, not a duration. Real per-fire
duration is only available from EFFIS (`FIREDATE` → `FINALDATE`).

### 2.5 Coverage ceiling and key overlap

INE AER exists only for 2019–2024. That bounds the demography-joined panel to six years.
ICNF independently spans 2001–2025, which is why a second fire-only panel is worth building.

Measured key overlap:

```
INE municipalities (per year) : 308
ICNF municipalities           : 278
GADM coded municipalities     : 285 (of 308 rows; 23 island codes are the string "NA")
INE ∩ ICNF                    : 278   unmatched: none
INE ∩ ICNF ∩ GADM             : 278   unmatched: none
```

The joined panel is therefore 278 × 6 = **1,668 rows**, with no key loss.

### 2.6 Fetchability

Probed directly:

| Source | Scriptable | Mechanism |
|---|---|---|
| GADM boundaries | yes | stable public URL |
| ICNF + INE workbooks | yes, once mirrored | GitHub Release asset on this repo |
| EFFIS (5 files, ~565 MB) | yes | public Google Drive folder |
| ICNF origin site | no | Angular SPA, no file link in HTML |
| INE origin site | no | refuses scripted requests |

The Google Drive folder `1PQkPYVMMe8UIoFqVLtuh9PdQolV-Fvxd` is public and contains
exactly the five EFFIS files. Verified end to end:

- small files download directly from `drive.google.com/uc?export=download&id=…`;
  `modis.ba.poly.prj` came back byte-identical (sha256 match) to the local copy.
- files above ~100 MB return a "Virus scan warning" interstitial carrying a form with
  `id`, `export`, `confirm=t`, `uuid`. Re-requesting
  `drive.usercontent.google.com/download` with those parameters returns the real bytes —
  verified: the first 100 bytes of `modis.ba.poly.shp` match the local file exactly,
  and the server answers range requests with `206`, so downloads are resumable.

## 3. Architecture

```
make fetch   scripts/fetch_data.py    network  → data/raw/
make data    scripts/build_data.py    data/raw → data/interim → data/processed
```

Both are idempotent. `make fetch` checksums what is already on disk and downloads only
what is missing or corrupt. `make data` runs ordered stages that each write one
artifact, so a mid-run failure does not discard completed work.

### 3.1 Fetch layer

A single manifest, `config/sources.yml`, is the only place a URL or checksum appears.
Each entry carries `kind`, `url`/`file_id`, `target`, `sha256`, `bytes`.

| kind | applies to | behavior |
|---|---|---|
| `http` | GADM, ICNF, INE | download, verify sha256 |
| `gdrive` | 5 EFFIS files | direct URL, fall back to confirm-token flow on interstitial, resume via range, verify sha256 |
| `manual` | escape hatch | print exact instructions, exit non-zero |

Checksums are committed, computed from the current working copies:

| File | Bytes | sha256 (first 16) |
|---|---|---|
| `modis.ba.poly.shp` | 323,262,544 | `f4a66dce6f917c94` |
| `modis.ba.poly.dbf` | 159,932,271 | `78bb22a258b82ddf` |
| `modis.ba.poly.shx` | 841,292 | `96059cb00c726244` |
| `modis.ba.poly.prj` | 144 | `c69b41ee32e7bda0` |
| `severity_2023.tiff` | 103,839,354 | `e533b09e5fcbc064` |
| `EstatisticasIncendiosSGIF-2001-2025.xlsx` | 1,265,335 | `598e16b3a16ca398` |
| `AER2019_II_01.xlsx` | 346,501 | `c373405379a48afc` |
| `AER2020_II_01.xlsx` | 368,632 | `ccc158e91755709f` |
| `AER2021_II_01.xlsx` | 357,501 | `e89bc0a57dde8d25` |
| `AER2022_II_01.xlsx` | 339,174 | `0c31ead751c1082e` |
| `AER2023_II_01.xlsx` | 333,809 | `5fa79e8801e9ec1c` |
| `AER2024_II_01.xlsx` | 294,984 | `8ae389f2e075ddd7` |
| `gadm41_PRT_2.json` | 939,819 | `1c23bb359e23ddc8` |

A wrong or truncated download fails loudly instead of producing a silently broken panel.

`scripts/download_data.py` is absorbed as `fetch_data.py --check`.

**Release to create:** tag `v0.1-data` on `rogerjeasy/sustainability-analytics`
(public), carrying the 7 lightweight workbooks (ICNF + 6 INE, ~3.3 MB total). These are
published government statistics from INE and ICNF; the release notes must attribute both.

### 3.2 Preprocess layer

Four ordered stages, selectable with `--stage`:

| Stage | Output | Shape |
|---|---|---|
| `ine` | `data/interim/ine_municipal_year.parquet` | 308 × 2019–2024 |
| `icnf` | `data/interim/icnf_municipal_year.parquet` | 2001–2025, 6,921 rows |
| `effis` | `data/interim/effis_municipal_year.parquet` | per-fire → centroid join → municipality-year |
| `panel` | `data/processed/panel_municipality_year.parquet` | 278 × 2019–2024 = 1,668 |
|  | `data/processed/fire_panel_municipality_year.parquet` | 2001–2025, 6,921 rows |
|  | `data/processed/ine_typology_nuts3.parquet` | NUTS III × APU/AMU/APR side table |

The fire panel carries no INE columns and so is not bounded by the 2019–2024 ceiling.

### 3.3 `src/` consolidation

`ine.py` and `io.py` currently both implement INE age-sheet reading with different
strategies. That duplication is resolved as part of this work:

- **`ine.py` becomes the single INE reader.** Its code-based row identification already
  yields 308 municipalities in every edition. It gains `load_indicators_year/all` for
  `II_01_01` + `II_01_01c`, with sign-stripped header matching and break-in-series capture.
- **`io.py`** keeps EFFIS, ICNF and boundaries. Its three INE functions are removed and
  callers repointed.
- **`merge.py`** gains `build_fire_panel()`; the `TODO(Roger)` INE attachment is completed.

Municipality area is computed from GADM geometry in `EPSG:3763`, not from
`raw.municipality_dimensions` in `config/paths.yml`, **which does not exist on disk**.
That stale path is removed rather than given a fetch entry.

## 4. Panel column contract

| Requirement | Columns | Source |
|---|---|---|
| population density | `pop_density` (break in series at 2021) | `II_01_01` |
| population growth rates | `growth_effective`, `growth_natural`, `growth_migratory` | `II_01_01` |
| birth / death rates | `birth_rate`, `death_rate` | `II_01_01` |
| age group shares | `share_0_14`, `share_15_24`, `share_25_64`, `share_65_plus`, `share_75_plus` | derived from counts |
| population counts | `pop_total`, `pop_0_14`, `pop_15_24`, `pop_25_64`, `pop_65_plus`, `pop_75_plus` | `II_01_03`/`_02` |
| aging (cross-check) | `aging_index`, `old_age_dependency`, `longevity_index` | derived + `II_01_01c` |
| number of fires | `n_fires` | ICNF |
| burned area (within) | `burned_ha_total`, `_forest`, `_shrub`, `_agric` — 2017+ only | ICNF `_NoConcelho` |
| burned area (ignited) | `burned_ha_total_ignited`, `_forest_ignited`, `_shrub_ignited`, `_agric_ignited` | ICNF `_IncendioInicioConc` |
| fire size distribution | 8 × `n_fires_<size>ha` | ICNF |
| cause | 6 × `cause_*` counts and `cause_*_share` | ICNF |
| duration | `n_fires_gt24h` (proxy); `effis_duration_days_mean`, `_max` (real) | ICNF; EFFIS |
| land cover of burned area | 9 × `lc_*_mean`, `percna2k_mean` | EFFIS |
| EFFIS fire size | `effis_n_fires`, `effis_burnt_ha_total`, `_median`, `_max` | EFFIS |
| derived | `burn_rate` = burned ha / municipality ha; `municipality_area_km2` | GADM |
| weather | **deferred** — no placeholder columns are emitted | — |

Granularity is one row per `(dtcc, year)` throughout.

Land cover here describes the composition of the area that **burned**, from ICNF's
forest/shrub/agriculture split and EFFIS's 9 classes. Municipality land cover as a
*predictor* would require CORINE/COS, which this project does not hold; that gap is
documented rather than approximated.

## 5. Validation

A `validate` stage writes `data/processed/validation_report.md` and exits non-zero on
violation. It asserts:

- `(dtcc, year)` is unique in every output;
- row counts match expectation: 1,668 joined; 6,921 fire panel (municipality count
  per year rises from 270 in 2001 to 278 from 2006 on — assert per-year counts, not a
  flat 278 × 25 product);
- all 278 join keys are present, and no merge multiplied rows;
- no column is entirely null;
- per-column null rates are reported, with `burned_ha_*` (pre-2017) and `pop_density`
  (2021 break) listed as known and expected.

## 6. Documentation

- `README.md` gains a **Getting the data** section: the two commands, what each writes,
  expected runtime and download size, and what to do when a checksum fails.
- `data/README.md` is updated for the mirrored sources and the release tag.
- `docs/data_dictionary.md` gains the full column contract with units, source sheet and
  caveats, including the 2017 burned-area boundary and the 2021 density break.

## 7. Tests

- `tests/test_ine.py`: sign-stripped header matching, `pop_density` present for all six
  years (regression for the 2021 bug), 308-municipality invariant per edition,
  break-in-series capture.
- `tests/test_merge.py`: 278-key join with no row multiplication, `(dtcc, year)`
  uniqueness, fire panel spans 2001–2025 independently of INE.
- Manifest test: every `config/sources.yml` entry has a target and a checksum.

Tests must not require network access or the 565 MB EFFIS files; INE/ICNF fixtures are
small enough to exercise directly, and EFFIS-dependent tests skip when the raw files
are absent.

## 8. Out of scope

- Weather acquisition (deferred by decision; the slot is documented, not stubbed).
- Municipality land cover as a predictor (CORINE/COS not held).
- Any change to the statistical or ML chapters beyond repointing them at the new panel.
