# Wildfires and Demographic Change in Portugal

Sustainability Analytics group project. We test whether rural depopulation and
demographic aging are associated with wildfire incidence in Portugal, and whether
municipality-level conditions can predict where fires occur.

**Hypothesis:** there is potential to reduce wildfire incidence by maintaining
abandoned meadows and agricultural land.

## Setup

```bash
conda env create -f environment.yml
conda activate wildfires
pre-commit install          # installs nbstripout — do not skip this
make fetch-check            # reports which raw data files you still need
```

`pip install -e .` runs as part of the env creation, so `import wildfires` works
from any notebook regardless of where the kernel started.

> No conda? Install [Miniforge](https://github.com/conda-forge/miniforge).
> `requirements.txt` exists as a fallback, but geopandas and rasterio via pip
> need a system GDAL and often fail on macOS.

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
| `data/processed/ine_typology_nuts3.parquet` | 462 | population by urban typology, NUTS III level |
| `data/processed/series_breaks.csv` | — | indicators INE flags with a break in series |
| `data/processed/validation_report.md` | — | contract checks and per-column null rates |

Read them with `from wildfires.io import load_panel, load_fire_panel`. Every
column is documented in [`docs/data_dictionary.md`](docs/data_dictionary.md).

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

### When a validation check fails

`make data` exits non-zero and names the failing check. It still writes
`data/processed/validation_report.md`, so start there — the check name says which
contract broke (row count, key uniqueness, an unexpectedly empty column) and the
detail column says by how much. A panel that fails its contract is not usable;
fix the stage rather than the threshold.

### Weather

Not yet acquired. Temperature, precipitation and wind are absent from the panel;
no placeholder columns are emitted. See [`data/README.md`](data/README.md) for the
intended source.

## Layout

```
config/paths.yml       every path in the project, relative to the repo root
data/                  gitignored except external/ and README — see data/README.md
src/wildfires/         shared code: loaders, cleaning, the merge, features, models
notebooks/             one numbered chapter per owner; the report itself
reports/               Jupyter Book config, bibliography, figures, slides
tests/                 pytest, mainly on the merge logic
docs/                  data dictionaries and the team workflow
archive/exploration/   the original exploratory notebooks, kept for reference
scripts/               data acquisition and build CLIs (fetch_data.py, build_data.py)
```

## Working rules

1. **Notebooks stay thin.** Anything that transforms data goes in
   `src/wildfires/` so that all four chapters read an identical dataset. If you
   are about to copy a cell from someone else's notebook, it belongs in `src/`.
2. **One owner per notebook.** Branch → PR → review by whoever is free. Because
   each chapter is a separate file, PRs do not collide.
3. **No paths in notebooks.** Add them to `config/paths.yml` and read
   `PATHS[...]`. Nobody else has `/Users/yourname/...`.
4. **Only `make data` writes to `data/interim/` and `data/processed/`.**
   Notebooks read those files; they never produce them.
5. **Never edit anything under `data/raw/`.**

## Chapters and owners

| Notebook                          | Owner  | Content                                           |
| --------------------------------- | ------ | ------------------------------------------------- |
| `00_introduction.ipynb`         | Adrian | SDG framing, motivation, research questions       |
| `01_data_cleaning.ipynb`        | Roger  | EFFIS + ICNF + INE → the analysis panel          |
| `02_eda.ipynb`                  | Roger  | Distributions, trends, maps, data-quality caveats |
| `03_statistical_analysis.ipynb` | Anibal | Question A: aging, depopulation, fire incidence   |
| `04_ml_fire_risk.ipynb`         | Samri  | Logistic regression, Random Forest, XGBoost       |
| `05_discussion.ipynb`           | Adrian | Findings, limitations, conclusion                 |

## Common commands

```bash
make fetch        # download every raw input, checksum-verified
make fetch-check  # report what is present, download nothing
make data         # build every interim + processed dataset, then validate
make test         # pytest
make lint         # ruff
make report       # execute notebooks → _build/html/index.html
```

Run `python scripts/build_data.py --stage ine` to rebuild a single stage.

## Data

Roughly 685 MB, gitignored, from EFFIS, ICNF, INE and GADM. See
[Getting the data](#getting-the-data) above for how to obtain it. Provenance,
access instructions and every known caveat are in
[`data/README.md`](data/README.md); the panel's column contract is in
[`docs/data_dictionary.md`](docs/data_dictionary.md) and the EFFIS field-level
reference in [`docs/EFFIS_data_dictionary.md`](docs/EFFIS_data_dictionary.md).
