# Analysis panel — data dictionary

`data/processed/panel_municipality_year.parquet`, built by `make data` via
`wildfires.merge.build_panel()`. One row per **(municipality, year)**:
278 mainland municipalities × 2019–2024 = **1,668 rows**.

Its sibling `data/processed/fire_panel_municipality_year.parquet`
(`build_fire_panel()`) carries the same fire columns across **2001–2025**
(6,921 rows) with no demography, so fire history is not capped by INE's
publication window. Every fire column below appears in both.

This file is the contract between the pipeline and chapters 02–04. Keep it
updated as columns are added. `make data` checks the panel against it and refuses
to emit a file that violates the contract — see `data/processed/validation_report.md`.

## Keys

| Column | Type | Meaning |
|---|---|---|
| `dtcc` | string(4) | Portuguese municipality code, zero-padded (`"0101"`). **The join key.** Matches GADM `CC_2` and ICNF `DTCC`. |
| `year` | int | Calendar year. |

Never join on municipality name: 308 municipalities carry only 306 distinct
`NAME_2` values, and GADM strips some internal spaces (`"CastelodePaiva"`).

## Geometry

| Column | Unit | Meaning |
|---|---|---|
| `municipality_area_km2` | km² | Municipality area from GADM level-2 geometry, measured in EPSG:3763 (PT-TM06/ETRS89). Computing area in EPSG:4326 would return square degrees. |

## From ICNF (`Estatisticas_Concelho`, 2001–2025)

### Counts

| Column | Source field | Meaning |
|---|---|---|
| `n_fires` | `Num_IncendiosRurais` | Rural fire count. Counts **ignitions**, whereas `effis_n_fires` counts **mapped burn scars** — they will not agree, and the gap is itself informative. |
| `n_fires_gt24h` | `Ninc_Sup24h` | **Count** of fires that burned longer than 24 h — not a duration. Proxy for suppression difficulty. |
| `n_fires_0_1ha` … `n_fires_1000_plus_ha` | `NIncRur_*` | Fire counts by size class (0–1, 1–10, 10–20, 20–50, 50–100, 100–500, 500–1000, 1000+ ha). |
| `cause_natural`, `cause_negligent`, `cause_intentional`, `cause_rekindle`, `cause_unknown`, `cause_uninvestigated` | `NInc_*` | Ignitions by attributed cause. `cause_uninvestigated` is large — treat it as its own category, **not** as missing. |

All counts are populated for the full 2001–2025 span.

### Burned area — two conventions, one seam

ICNF publishes two burned-area families that answer different questions, and
switched between them in 2017 **with no overlap year**. Both are carried,
distinctly named, and never silently combined.

| Column | Source field | Years populated | Measures |
|---|---|---|---|
| `burned_ha_total`, `burned_ha_forest`, `burned_ha_shrub`, `burned_ha_agric` | `AreaArd*_NoConcelho` | **2017–2025** | Hectares that burned **within** this municipality. |
| `burned_ha_total_ignited`, `burned_ha_forest_ignited`, `burned_ha_shrub_ignited`, `burned_ha_agric_ignited` | `AreaArd*_IncendioInicioConc` | **2001–2016** | Hectares of fires that **ignited** in this municipality, wherever they went on to burn. |

Because the analysis panel covers 2019–2024 only, **every `*_ignited` column is
100% null there**. That is by construction, not missing data, and the validation
report lists it as an expected gap.

### Derived rates

| Column | Unit | Definition | Years |
|---|---|---|---|
| `burn_rate` | fraction | `burned_ha_total / (municipality_area_km2 × 100)` | 2017–2025 |
| `burn_rate_ignited` | fraction | `burned_ha_total_ignited / (municipality_area_km2 × 100)` | 2001–2016 |

`burn_rate_ignited` is not bounded by 1 even in principle — a municipality can
start fires that go on to burn more land than the municipality contains. In the
data as built it never does: the observed maxima are 0.78 (`burn_rate`) and
0.83 (`burn_rate_ignited`). A value above ~1.5 means an area-unit mismatch, and
that is what the validation stage checks for.

## From EFFIS (burn polygons spatially joined to municipality, 2016–2025)

EFFIS coverage begins in 2016, so all of these are null before it — and null in
any municipality-year where no fire was large enough to be resolved from satellite
imagery. Roughly 59% of panel rows are null here.

**Do not read those nulls as zeros.** They mark an absence of *mapped* fire, not an
absence of fire: of the 981 panel rows with no EFFIS record, 970 still carry ICNF
ignitions — a median of 13, and one municipality-year with 266. Chapter 01 shows
this. Treating EFFIS nulls as zero fire-activity would bias any model that uses them.

| Column | Meaning |
|---|---|
| `effis_n_fires` | Count of EFFIS burn polygons attributed to this municipality-year. |
| `effis_burnt_ha_total` | Sum of `AREA_HA`. |
| `effis_burnt_ha_median` | Median fire size. |
| `effis_burnt_ha_max` | Largest single fire. |
| `effis_duration_days_mean`, `effis_duration_days_max` | Per-fire duration, `FINALDATE − FIREDATE`. The only real duration measure in the panel. |
| `lc_transit_mean` | Mean % transitional woodland-shrub (CLC 324) **of burned area** — the land-abandonment indicator. Portugal: 26.4% vs 8.3% EU-wide. |
| `lc_broadlea_mean`, `lc_conifer_mean`, `lc_mixed_mean`, `lc_scleroph_mean`, `lc_othernatlc_mean`, `lc_agriareas_mean`, `lc_artifsurf_mean`, `lc_otherlc_mean` | Mean land-cover composition of burned area, percentages. |
| `percna2k_mean` | Mean % of burn scar inside a Natura 2000 site. Clipped to 100 (the source maxes at 100.25, a rounding artefact). |

## From INE (Anuário Estatístico Regional, 2019–2024)

Present in the analysis panel only. The 2019–2024 window is INE's publication
range, not a modelling choice.

| Column | Unit | Meaning |
|---|---|---|
| `territory` | string | Município name as published by INE. Labelling only — never a join key. |
| `pop_total` | residents | Resident population. |
| `pop_0_14`, `pop_15_24`, `pop_25_64`, `pop_65_plus`, `pop_75_plus` | residents | Resident population by age group. |
| `share_0_14`, `share_15_24`, `share_25_64`, `share_65_plus`, `share_75_plus` | **%** | Age group ÷ `pop_total` × 100, computed here. These are percentages, not fractions — `share_65_plus` has a median of 26.9, not 0.269. |
| `aging_index` | per 100 | INE's *índice de envelhecimento*: residents aged 65+ per 100 aged 0–14. Computed here. |
| `old_age_dependency` | per 100 | Residents aged 65+ per 100 aged 15–64. Computed here. |
| `pop_density` | residents/km² | As published by INE. **Break in series at 2021** — see caveats. |
| `growth_effective`, `growth_natural`, `growth_migratory` | % | Population growth rates as published. |
| `birth_rate`, `death_rate` | ‰ | Crude rates as published. |
| `aging_index_ine`, `old_age_dependency_ine` | per 100 | INE's own published values for the two indices above. Kept alongside the computed equivalents so the two can be cross-checked rather than silently conflated; they agree to INE's published rounding (e.g. 232.794 computed vs 232.8 published). |
| `renewal_index` | per 100 | INE's *índice de renovação da população em idade activa*: residents aged 20–29 per 100 aged 55–64. Published only, not recomputed. |
| `longevity_index` | per 100 | INE's *índice de longevidade*: residents aged 75+ per 100 aged 65+. Published only, not recomputed. |

## Side tables

| File | Grain | Contents |
|---|---|---|
| `data/processed/ine_typology_nuts3.parquet` | NUTS III × year × typology | Population by urban typology (APU/AMU/APR). These INE sheets (`II_01_04`/`II_01_05`) carry **no municipality code**, so they cannot join to the panel and are kept separate. AER2022 does not publish them, so **2022 is absent** — a real gap, left as one. |
| `data/processed/series_breaks.csv` | indicator × year | Every indicator INE flags with `┴` (break in series). Recorded as metadata; values are never adjusted. |
| `data/processed/validation_report.md` | — | Contract checks and per-column null rates from the last `make data`. |

## Caveats that change interpretation

- **`burned_ha_*` vs `burned_ha_*_ignited`.** The first is area burned *within*
  the municipality (ICNF `_NoConcelho`, **2017–2025 only**); the second is the
  area of fires that *ignited* there (`_IncendioInicioConc`, **2001–2016 only**).
  They answer different questions and are never combined by the pipeline.
  **No single ICNF burned-area column spans 2017**, so any trend crossing that
  year is a splice of two different measures — do it explicitly, in one place,
  and label the result a splice rather than a measurement.
- **`n_fires_gt24h` is a count, not a duration.** It is the number of fires that
  burned longer than 24 h. Real per-fire duration is `effis_duration_days_*`,
  and exists only from 2016 (EFFIS coverage).
- **`pop_density` has a break in series at 2021.** INE flags it (Censos 2021
  re-basing). Values are as published and are not adjusted; `2020 → 2021` is not
  a like-for-like comparison.
- **`lc_*_mean` describes what burned, not the municipality.** These are the mean
  land-cover composition of EFFIS burn perimeters. Municipality land cover as a
  predictor would need CORINE/COS, which this project does not hold.
- **EFFIS lowered its minimum mapped fire size around 2020.** Apply
  `wildfires.clean.apply_size_floor` (`CONVENTIONS.min_fire_ha`, default 30 ha)
  before reading any cross-year EFFIS trend.
- **Nothing is imputed, interpolated or smoothed.** INE conventional signs
  (`x`, `…`, `§`, `ə`, `//`) become `NaN`. Missing stays missing.

## Known limitations

- Fires crossing a municipal border are attributed to a single municipality
  (the one containing the polygon's representative point).
- Municipality-years with no *mapped* EFFIS fire appear as null, not zero, and
  most of them did have fires. Decide per analysis what to do with them, but do
  not assume they were quiet years.
- Weather (temperature, precipitation, wind) is **not in the panel**. No
  placeholder columns are emitted. See `data/README.md`.
