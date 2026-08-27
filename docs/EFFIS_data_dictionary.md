# EFFIS Burnt Area Database — data dictionary

Field-by-field reference for the EFFIS burnt-area polygon layer.

**Snapshot:** 105,149 records, `FIREDATE` 2016-02-07 → 2026-08-25, 50 country codes, EPSG:4326.

**Source:** <https://maps.effis.emergency.copernicus.eu/effis> (WFS, `outputformat=SHAPEZIP`)

---

## Identity and time

| Column | Meaning |
|---|---|
| `id` | EFFIS internal record ID. Numeric string, unique across all 105,149 rows. Not stable across downloads — don't use it as a persistent key between refreshes. |
| `FIREDATE` | Date the fire was first detected/started. Range in this file: 2016-02-07 → 2026-08-25. **Mixed ISO precision** — some values carry fractional seconds, which is why `format="ISO8601"` is required. |
| `FINALDATE` | Date the fire was considered finished. Median duration is 0.02 days and 43% of records have `FINALDATE == FIREDATE`, so for most fires this carries no extra information. The tail is real though — max 58 days. `FINALDATE - FIREDATE` is a usable fire-duration variable if you restrict to larger fires. |
| `LASTUPDATE` | When EFFIS last reprocessed that record. Ranges 2022-01-26 → today. The mass values (14,511 rows sharing one timestamp) are bulk reprocessing batches, not fire events. Useful only for provenance/reproducibility — note it when you cite a snapshot date. |

## Administrative location

| Column | Meaning |
|---|---|
| `COUNTRY` | Two-letter code, 50 present. **Not pure ISO**: Greece is `EL` (not GR), the UK is `UK` (not GB), Kosovo is `KS`. |
| `PROVINCE` | For Portugal this is **NUTS3** — 25 values, exactly Portugal's NUTS3 regions including Madeira and Açores. Clean, and joins directly to Eurostat demography. Not verified as NUTS3 outside Portugal (see caveat below). |
| `COMMUNE` | For Portugal, the **freguesia** (civil parish), not the municipality — 1,374 distinct values in the PT subset. Free-text name, no code. 47.9% of rows EU-wide are `"N.A."` (0% for PT). This is the field bypassed by the spatial join in notebook section 8. |

## Size

| Column | Meaning |
|---|---|
| `AREA_HA` | Burned area of that polygon, in hectares. **Integers only**, 0 to 96,610. Matches the polygon's own geometry to ~1%, so it is genuinely the polygon area — but it's attached to a single `COMMUNE` label regardless of how many the fire crossed. The `0` values are sub-hectare fires rounded down, not missing data. |

## Land-cover composition — the abandonment-relevant block

Nine columns giving the CLC composition of each burn scar as **percentages summing to 100** (true for
98.4% of rows; 1,722 rows are entirely null and 1.6% sum to zero).

| Column | CLC grouping |
|---|---|
| `BROADLEA` | Broad-leaved forest (311) |
| `CONIFER` | Coniferous forest (312) |
| `MIXED` | Mixed forest (313) |
| `SCLEROPH` | Sclerophyllous vegetation (323) — maquis/garrigue |
| `TRANSIT` | **Transitional woodland-shrub (324)** |
| `OTHERNATLC` | Other natural land cover — natural grassland, moors/heathland, sparsely vegetated open spaces (321, 322, 33x) |
| `AGRIAREAS` | Agricultural areas (2xx) |
| `ARTIFSURF` | Artificial surfaces (1xx) |
| `OTHERLC` | Remainder — wetlands, water (4xx, 5xx) |

The exact class-to-column aggregation for `OTHERNATLC` and `OTHERLC` is EFFIS's own grouping; worth
confirming against their documentation before you put the mapping in a report.

`TRANSIT` is the one that matters for this project. CLC 324 is the successional stage between
cleared/farmed land and closed forest — it is what abandoned plots become. And Portugal is a striking
outlier: **26.4% of Portuguese burned area is transitional woodland-shrub against 8.3% EU-wide**.
That's the abandonment–fire link showing up directly in the fire record, before anyone has touched a
CLC change layer.

## Status and geometry

| Column | Meaning |
|---|---|
| `PERCNA2K` | % of the burn scar inside a Natura 2000 protected site. Strongly bimodal — 80.2% are exactly 0 and 10.4% are ≥100, so fires are usually wholly in or wholly out. Max is 100.25, a rounding artefact; clip to 100. |
| `CLASS` | **A recency/provenance flag, not a fire type.** `FireSeason` (102,577 rows) is the consolidated archive. `30DAYS` / `7DAYS` / `1DAY` appear only in the current year — they're rolling near-real-time windows appended on top of the current season. Those records are provisional and will be revised. For any historical analysis, filter to `CLASS == "FireSeason"`. |
| `geometry` | The burn perimeter polygon, EPSG:4326. Note EFFIS's `.prj` declares an unnamed WGS84 GEOGCS, so geopandas won't recognise it as EPSG:4326 until you retag it — that's the `set_crs(..., allow_override=True)` line in the notebook. |

---

Notes:

- **Fire counts are not comparable across years.** EFFIS lowered its minimum mapped fire size around
  2020: the 5th-percentile fire is ~35 ha in 2016–17 but ~1 ha from 2021 on, and the median
  Portuguese fire falls from 131 ha to 5 ha purely from detection changes. Apply a constant size
  floor (e.g. ≥30 ha) before reading any trend.
- **GeoPackage column names are case-insensitive.** A derived `area_ha` collides with the original
  `AREA_HA` and GDAL will refuse to create the layer. Rename on export.
- **`PROVINCE` is only verified as NUTS3 for Portugal.** Italy shows 188 distinct values and France
  74 — more than either country has NUTS3 regions.