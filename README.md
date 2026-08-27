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
make data                   # reports which raw data files you still need
```

`pip install -e .` runs as part of the env creation, so `import wildfires` works
from any notebook regardless of where the kernel started.

> No conda? Install [Miniforge](https://github.com/conda-forge/miniforge).
> `requirements.txt` exists as a fallback, but geopandas and rasterio via pip
> need a system GDAL and often fail on macOS.

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
scripts/               data acquisition helper
```

## Working rules

1. **Notebooks stay thin.** Anything that transforms data goes in
   `src/wildfires/` so that all four chapters read an identical dataset. If you
   are about to copy a cell from someone else's notebook, it belongs in `src/`.
2. **One owner per notebook.** Branch → PR → review by whoever is free. Because
   each chapter is a separate file, PRs do not collide.
3. **No paths in notebooks.** Add them to `config/paths.yml` and read
   `PATHS[...]`. Nobody else has `/Users/yourname/...`.
4. **Only `01_data_cleaning.ipynb` writes to `data/processed/`.**
5. **Never edit anything under `data/raw/`.**

## Chapters and owners

| Notebook | Owner | Content |
|---|---|---|
| `00_introduction.ipynb` | Adrian | SDG framing, motivation, research questions |
| `01_data_cleaning.ipynb` | Roger | EFFIS + ICNF + INE → the analysis panel |
| `02_eda.ipynb` | Roger | Distributions, trends, maps, data-quality caveats |
| `03_statistical_analysis.ipynb` | Anibal | Question A: aging, depopulation, fire incidence |
| `04_ml_fire_risk.ipynb` | Samri | Logistic regression, Random Forest, XGBoost |
| `05_discussion.ipynb` | Adrian | Findings, limitations, conclusion |

## Common commands

```bash
make panel     # rebuild data/processed/panel_municipality_year.parquet
make test      # pytest
make lint      # ruff
make report    # execute notebooks → reports/_build/html/index.html
```

## Data

Roughly 685 MB, gitignored, from EFFIS, ICNF, INE and GADM. Provenance, access
instructions and every known caveat are in [`data/README.md`](data/README.md).
The EFFIS field-level reference is [`docs/EFFIS_data_dictionary.md`](docs/EFFIS_data_dictionary.md).
