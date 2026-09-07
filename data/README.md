# Data

`data/raw/`, `data/interim/` and `data/processed/` are **gitignored** — together
they are ~685 MB. Only this file and `data/external/` are committed.

After cloning, run `make fetch` to download everything (checksum-verified), or
`make fetch-check` to see what is missing without downloading. Every URL and
checksum lives in `config/sources.yml` — that is the only place they appear.

## Layers

| Folder | Tracked | Rule |
|---|---|---|
| `raw/` | no | Exactly as downloaded. **Never edit by hand, never write here from a notebook.** |
| `interim/` | no | Partially processed, reproducible from `raw/`. |
| `processed/` | no | Analysis-ready. Written only by `make data`. |
| `external/` | **yes** | Small hand-maintained lookups (crosswalks, code tables). |

## Sources

### `raw/effis/` — EFFIS burnt-area polygons
- **Source:** Copernicus EMS, <https://forest-fire.emergency.copernicus.eu/>
- **Access:** account request, then WFS download with `outputformat=SHAPEZIP`
- **Snapshot:** retrieved 2026-08-25 — 105,149 records, `FIREDATE` 2016-02-07 → 2026-08-25, EPSG:4326
- **Files:** `modis.ba.poly.{shp,shx,dbf,prj}`, `severity_2023.tiff`
- **Mirror:** `make fetch` pulls these from a public Google Drive folder, so no
  EFFIS account is needed to reproduce the pipeline. The account request above is
  only needed to refresh the snapshot.
- **Subsetting:** the shapefile covers all of Europe and North Africa (105,149
  polygons, 40 countries). `make data`'s first stage filters it to ES/FR/IT/PT and
  writes `data/interim/effis/effis_subset_ES-FR-IT-PT.{gpkg,csv}`. Do not create
  those files by hand — they are build output, reproducible from `raw/` alone.
- **Caveats:** see `docs/EFFIS_data_dictionary.md`. The three that bite:
  1. filter to `CLASS == "FireSeason"` for any historical analysis;
  2. the `.prj` needs `set_crs(..., allow_override=True)`;
  3. EFFIS lowered its minimum mapped fire size ~2020 — apply a constant size
     floor before reading any cross-year trend.

### `raw/icnf/` — ICNF rural fire statistics
- **Source:** Instituto da Conservação da Natureza e das Florestas
- **File:** `EstatisticasIncendiosSGIF-2001-2025.xlsx`
- **Coverage:** 2001–2025, mainland Portugal
- **Sheets:** country / district / NUTS3 / **concelho** (municipality) + `Legendas` (field glossary, in Portuguese)
- **Why it matters:** the `Estatisticas_Concelho` sheet carries `DTCC` (the
  municipality code used as this project's join key), the fire-cause breakdown
  (`NInc_Natural`, `NInc_Negligente`, `NInc_Intencionais`, `NInc_Reacendimentos`,
  …) and `Ninc_Sup24h` (fires burning >24 h).
- **Mirror:** `make fetch` pulls this from the `v0.1-data` GitHub Release on this repo.
- **Caveats:**
  - Missing values are the literal string `"(sem informação)"`.
  - **Two burned-area conventions, switched in 2017 with no overlap year.**
    `AreaArd*_NoConcelho` (area burned *within* the municipality) is populated
    **2017–2025**; `AreaArd*_IncendioInicioConc` (area of fires that *ignited*
    there) is populated **2001–2016**. The pipeline carries both under distinct
    names (`burned_ha_*` and `burned_ha_*_ignited`) and never coalesces them.
    No single column spans 2017 — see `docs/data_dictionary.md`.

### `raw/ine/` — INE Anuário Estatístico Regional
- **Source:** Instituto Nacional de Estatística, <https://www.ine.pt/>
- **Files:** `AER2019_II_01.xlsx` … `AER2024_II_01.xlsx` (chapter II.01, Population)
- **Sheet `II_01_01`:** population density and demographic rates — **at município
  level**, with NUTS I/II/III columns.
- **Age sheets:** resident population totals and younger age groups are in
  `II_01_03` for 2019–2021 and 2023–2024, and `II_01_02` for 2022. The older
  age groups are in companion `II_01_03c`/`II_01_02c` sheets for 2019–2022.
  These files contain município/concelho rows, not freguesia rows.
- **Sheets `II_01_01` + `II_01_01c`:** population density, effective/natural/migratory
  growth, crude birth and death rates, and the aging indices — município level. These
  are the source of every demographic rate in the panel.
- **Sheets `II_01_04`/`II_01_05`:** population by urban typology (APU/AMU/APR) — **NUTS III
  level, with no municipality code**. They cannot join to the panel and are written to
  `data/processed/ine_typology_nuts3.parquet` instead. AER2022 does not publish them, so
  2022 is absent from that table — a real gap, left as one.
- **Conventional signs:** `x`, `…`, `§`, `ə`, `//` mark missing or unreliable values and
  become `NaN`. `┴` marks a break in series and is recorded in
  `data/processed/series_breaks.csv` — INE flags one on population density in 2021
  (Censos 2021 re-basing), so density is not strictly comparable across 2020 → 2021.
- **Mirror:** `make fetch` pulls all six workbooks from the `v0.1-data` GitHub Release.
- **Caveat:** header rows and sheet names vary by year; use `wildfires.ine` rather than
  reading workbook sheets directly.

### `raw/boundaries/` — administrative geometry
- **`gadm41_PRT_2.json`** — GADM v4.1 level 2 = the 308 Portuguese concelhos.
  `CC_2` is the 4-digit municipality code and matches ICNF's `DTCC`.
  **Join on the code, never the name:** 308 municipalities have only 306 distinct
  `NAME_2` values, and GADM strips some internal spaces (`"CastelodePaiva"`).
- **GISCO NUTS** (not yet downloaded) — <https://ec.europa.eu/eurostat/web/gisco/geodata/statistical-units/territorial-units-statistics>

### `raw/weather/` — **DEFERRED, NOT ACQUIRED**
Wind, temperature and precipitation are **deliberately not in the panel**. No
placeholder columns are emitted, so no analysis can accidentally treat them as
present-but-missing. Intended source if the project picks this up: ERA5-Land
monthly means via the Copernicus CDS API (<https://cds.climate.copernicus.eu>).
**Registration takes time — start early.**

## The join

```
EFFIS polygons (freguesia, no code)
        │  spatial join on representative point → GADM level 2
        ▼
   dtcc (4-digit municipality code)  ←── ICNF Estatisticas_Concelho (DTCC)
        │                            ←── INE AER (7-digit code → last 4 = dtcc)
        ▼
data/processed/fire_panel_municipality_year.parquet   6,921 rows, 2001–2025
        │  inner join on INE demography
        ▼
data/processed/panel_municipality_year.parquet        1,668 rows, 2019–2024
```

The fire panel exists so the 18 years of fire history that predate INE AER stay
usable. The analysis panel's inner join is deliberate: INE covers 308
municipalities for 2019–2024, ICNF covers 278 mainland ones, and the 278 in both
are the analysis population — every one of them matches.

EFFIS's `COMMUNE` is the *freguesia* (civil parish), one level finer than the
concelho, and is free text with no code — which is why it cannot be joined
directly and needs the spatial step.
