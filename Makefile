.PHONY: help setup fetch fetch-check data panel test lint report report-serve clean-report

help:
	@echo "setup       - create the conda env and install pre-commit hooks"
	@echo "fetch       - download every raw input (checksum-verified, ~565 MB)"
	@echo "fetch-check - report which raw inputs are present, download nothing"
	@echo "data        - build interim + processed datasets from data/raw"
	@echo "panel       - alias for 'data'"
	@echo "test        - run pytest"
	@echo "lint        - run ruff"
	@echo "report      - build the static site into _build/html"
	@echo "report-serve - live preview in a browser"

setup:
	conda env create -f environment.yml || conda env update -f environment.yml --prune
	@echo "Now run: conda activate wildfires && pre-commit install"

fetch:
	python scripts/fetch_data.py

fetch-check:
	python scripts/fetch_data.py --check

data:
	python -c "from wildfires.merge import build_panel; p = build_panel(save=True); print(p.shape)"

panel: data

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
