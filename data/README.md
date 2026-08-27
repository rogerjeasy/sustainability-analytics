# Data

`data/raw/`, `data/interim/` and `data/processed/` are **gitignored** — together
they are ~685 MB. Only this file and `data/external/` are committed.

After cloning, run `make data` to see which sources are missing on your machine.

## Layers

| Folder | Tracked | Rule |
|---|---|---|
| `raw/` | no | Exactly as downloaded. **Never edit by hand, never write here from a notebook.** |
| `interim/` | no | Partially processed, reproducible from `raw/`. |
| `processed/` | no | Analysis-ready. Written only by `01_data_cleaning.ipynb`. |
| `external/` | **yes** | Small hand-maintained lookups (crosswalks, code tables). |

## Sources

### `raw/effis/` — EFFIS burnt-area polygons
- **Source:** Copernicus EMS, <https://forest-fire.emergency.copernicus.eu/>
- **Access:** account request, then WFS download with `outputformat=SHAPEZIP`
- **Snapshot:** retrieved 2026-08-25 — 105,149 records, `FIREDATE` 2016-02-07 → 2026-08-25, EPSG:4326
- **Files:** `modis.ba.poly.{shp,shx,dbf,prj}`, `severity_2023.tiff`
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
- **Caveat:** missing values are the literal string `"(sem informação)"`, and the
  `AreaArd*_No*` columns are empty for the early years.

### `raw/ine/` — INE Anuário Estatístico Regional
- **Source:** Instituto Nacional de Estatística, <https://www.ine.pt/>
- **Files:** `AER2019_II_01.xlsx` … `AER2024_II_01.xlsx` (chapter II.01, Population)
- **Sheet `II_01_01`:** population density and demographic rates — **at município
  level**, with NUTS I/II/III columns.
- **Age sheet:** resident population totals and age groups by sex are in
  `II_01_03` for 2019–2021 and 2023–2024, and `II_01_02` for 2022. These files
  contain município/concelho rows, not freguesia rows.
- **Caveat:** header rows vary by year; use the shared loaders in
  `wildfires.io` rather than reading workbook sheets directly.

### `raw/boundaries/` — administrative geometry
- **`gadm41_PRT_2.json`** — GADM v4.1 level 2 = the 308 Portuguese concelhos.
  `CC_2` is the 4-digit municipality code and matches ICNF's `DTCC`.
  **Join on the code, never the name:** 308 municipalities have only 306 distinct
  `NAME_2` values, and GADM strips some internal spaces (`"CastelodePaiva"`).
- **GISCO NUTS** (not yet downloaded) — <https://ec.europa.eu/eurostat/web/gisco/geodata/statistical-units/territorial-units-statistics>

### `raw/weather/` — **NOT YET ACQUIRED**
Wind, temperature and precipitation are missing from the project and were flagged
as needed. Plan: ERA5-Land monthly means via the Copernicus CDS API
(<https://cds.climate.copernicus.eu>). **Registration takes time — start early.**

### `raw/eurostat/` — population change (optional)
`demo_r_gind3` at NUTS3. Only needed if the analysis moves up from municipality
to NUTS3 level; INE already provides municipality-level demography.

## The join

```
EFFIS polygons (freguesia, no code)
        │  spatial join on centroid → GADM level 2
        ▼
   dtcc (4-digit municipality code)  ←── ICNF Estatisticas_Concelho (DTCC)
        │                            ←── INE AER (município name → dtcc)
        ▼
data/processed/panel_municipality_year.parquet    one row per (dtcc, year)
```

EFFIS's `COMMUNE` is the *freguesia* (civil parish), one level finer than the
concelho, and is free text with no code — which is why it cannot be joined
directly and needs the spatial step.
