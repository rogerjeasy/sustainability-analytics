.PHONY: help setup data panel test lint report clean-report

help:
	@echo "setup   - create the conda env and install pre-commit hooks"
	@echo "data    - report which raw files are present/missing"
	@echo "panel   - build data/processed/panel_municipality_year.parquet"
	@echo "test    - run pytest"
	@echo "lint    - run ruff"
	@echo "report  - execute notebooks and build reports/_build/html"

setup:
	conda env create -f environment.yml || conda env update -f environment.yml --prune
	@echo "Now run: conda activate wildfires && pre-commit install"

data:
	python scripts/download_data.py

panel:
	python -c "from wildfires.merge import build_panel; p = build_panel(save=True); print(p.shape)"

test:
	pytest -q

lint:
	ruff check src tests

report:
	jupyter-book build reports --path-output reports

clean-report:
	rm -rf reports/_build
