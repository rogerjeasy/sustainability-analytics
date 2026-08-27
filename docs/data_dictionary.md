# Analysis panel — data dictionary

`data/processed/panel_municipality_year.parquet`, built by
`wildfires.merge.build_panel()`. One row per **(municipality, year)**.

Keep this file updated as columns are added — it is the contract between
chapter 01 and chapters 02–04.

## Keys

| Column | Type | Meaning |
|---|---|---|
| `dtcc` | string(4) | Portuguese municipality code, zero-padded (`"0101"`). Join key. Matches GADM `CC_2` and ICNF `DTCC`. |
| `year` | int | Calendar year. |

## From EFFIS (spatially joined to municipality)

| Column | Meaning |
|---|---|
| `n_fires` | Count of EFFIS burn polygons attributed to this municipality-year. |
| `burnt_ha_total` | Sum of `AREA_HA`. |
| `burnt_ha_median` | Median fire size. |
| `burnt_ha_max` | Largest single fire. |
| `transit_mean` | Mean % transitional woodland-shrub (CLC 324) of burned area — **the abandonment indicator**. Portugal: 26.4% vs 8.3% EU-wide. |
| `broadlea_mean`, `conifer_mean`, `mixed_mean`, `scleroph_mean`, `othernatlc_mean`, `agriareas_mean`, `artifsurf_mean`, `otherlc_mean` | Mean land-cover composition of burned area, percentages. |
| `percna2k_mean` | Mean % of burn scar inside a Natura 2000 site. |

## From ICNF (`Estatisticas_Concelho`)

| Column | Meaning |
|---|---|
| `Num_IncendiosRurais` | Rural fire count. Note this counts *ignitions*, whereas `n_fires` counts *mapped burn scars* — they will not agree, and the gap is itself informative. |
| `Ninc_Sup24h` | Fires burning longer than 24 h. Proxy for suppression difficulty / response. |
| `NInc_Natural` | Ignitions attributed to natural causes. |
| `NInc_Negligente` | Negligence. |
| `NInc_Intencionais` | Intentional. |
| `NInc_Reacendimentos` | Rekindles. |
| `NInc_Desconhecida` | Unknown cause. |
| `NInc_NaoInvestigados` | Not investigated. Large — treat as its own category, not as missing. |

## From INE (to be added — see TODO in `merge.build_panel`)

| Column | Meaning |
|---|---|
| `pop_density` | Residents per km². |
| `growth_effective` | Effective population growth rate, %. |
| `growth_natural` | Natural growth rate. |
| `growth_migratory` | Migratory growth rate. |
| `birth_rate`, `death_rate` | Crude rates, ‰. |

The resident population and age-by-sex table is loaded separately from
`II_01_03` for 2019–2021 and 2023–2024, and `II_01_02` for 2022. Its `Total`
column and age-group columns are at município/concelho level; the AER files do
not provide freguesia-level rows.

**Coverage constraint:** the AER files cover 2019–2024, so attaching demography
restricts the panel's usable window to those years.

## Known limitations

- Fires crossing a municipal border are attributed to a single municipality
  (the one containing the polygon's representative point).
- EFFIS fire counts are not comparable across the ~2020 detection change without
  a constant size floor (`CONVENTIONS.min_fire_ha`, default 30 ha).
- Municipality-years with no fire appear with nulls after the outer join;
  decide per analysis whether those are zeros or missing.
