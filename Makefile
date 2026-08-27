.PHONY: help setup data panel test lint report report-serve clean-report

help:
	@echo "setup   - create the conda env and install pre-commit hooks"
	@echo "data    - report which raw files are present/missing"
	@echo "panel   - build data/processed/panel_municipality_year.parquet"
	@echo "test    - run pytest"
	@echo "lint    - run ruff"
	@echo "report  - build the static site into _build/html"
	@echo "report-serve - live preview in a browser"

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
	jupyter-book build --html

report-serve:
	jupyter-book start

clean-report:
	rm -rf _build
