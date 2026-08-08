.PHONY: help install sample data real api test lint clean all

PY ?= python

help:
	@echo "PharmaTarget"
	@echo ""
	@echo "  make install   install python dependencies"
	@echo "  make sample    synthetic data + full pipeline, small (~2 min)"
	@echo "  make data      synthetic data + full pipeline, full scale (~8 min)"
	@echo "  make real      pipeline against downloaded CMS data"
	@echo "  make download  fetch CMS source files into data/raw/"
	@echo "  make api       serve the API + dashboard on :8000"
	@echo "  make test      run the test suite"
	@echo "  make lint      ruff"
	@echo "  make all       sample + test + lint"
	@echo ""
	@echo "  make web-install   npm install for the React app"
	@echo "  make web           Vite dev server on :5173 (proxies /api to :8000)"
	@echo "  make web-build     build web/dist, which the API then serves"
	@echo ""
	@echo "Start here:  make install && make sample && make api"
	@echo "Frontend:    make web-install && make web   (needs the API running)"

install:
	$(PY) -m pip install -r requirements.txt

sample:
	$(PY) -m src.pipeline --synthetic --sample

data:
	$(PY) -m src.pipeline --synthetic

download:
	$(PY) -m src.ingest.download

real:
	$(PY) -m src.pipeline

sensitivity:
	$(PY) -m src.etl.build_marts --all-modes

api:
	$(PY) -m uvicorn api.main:app --host 0.0.0.0 --port 8000

# --- frontend -------------------------------------------------------------
# `make web` runs Vite on :5173 and proxies /api to :8000, so the browser sees
# one origin and CORS never comes up. `make web-build` emits web/dist, which
# api/main.py serves automatically -- one process, one URL, nothing to deploy
# twice.
web-install:
	cd web && npm install

web:
	cd web && npm run dev

web-build:
	cd web && npm run build

web-check:
	cd web && npm run typecheck

test:
	$(PY) -m pytest tests/ -q

lint:
	$(PY) -m ruff check src api tests

clean:
	rm -rf data/interim data/processed data/manifest.json
	rm -rf .pytest_cache .ruff_cache __pycache__

all: sample test lint
