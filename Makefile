.PHONY: help install install-lock sample demo data real run stages api test coverage lint \n        web-install web web-build web-check web-test docker ci clean all

PY ?= python

help:
	@echo "PharmaTarget"
	@echo ""
	@echo "  make install   install python dependencies (ranges)"
	@echo "  make install-lock  install the exact versions CI uses"
	@echo "  make demo      sample pipeline, then serve the app on :8000 (~3 min)"
	@echo "  make sample    synthetic data + full pipeline, small (~3 min)"
	@echo "  make data      synthetic data + full pipeline, full scale (~8 min)"
	@echo "  make real      pipeline against downloaded CMS data"
	@echo "  make run       resumable runner: only the stale stages (src/run.py)"
	@echo "  make stages    list every stage and whether it is stale"
	@echo "  make download  fetch CMS source files into data/raw/"
	@echo "  make api       serve the API + dashboard on :8000"
	@echo "  make test      run the test suite"
	@echo "  make coverage  tests with a coverage report"
	@echo "  make ci        everything CI checks: lint, tests, web typecheck/tests/build"
	@echo "  make docker    build and run the production image on :8000"
	@echo "  make lint      ruff"
	@echo "  make all       sample + test + lint"
	@echo ""
	@echo "  make web-install   npm install for the React app"
	@echo "  make web           Vite dev server on :5173 (proxies /api to :8000)"
	@echo "  make web-build     build web/dist, which the API then serves"
	@echo ""
	@echo "Start here:  make install && make demo"
	@echo "Frontend:    make web-install && make web   (needs the API running)"

install:
	$(PY) -m pip install -r requirements.txt

install-lock:
	$(PY) -m pip install -r requirements.lock

sample:
	$(PY) -m src.pipeline --synthetic --sample

data:
	$(PY) -m src.pipeline --synthetic

download:
	$(PY) -m src.ingest.download

demo: sample api

real:
	$(PY) -m src.pipeline

# Resumable runner: skips every stage whose artifact is newer than its sources.
run:
	$(PY) -m src.run

stages:
	$(PY) -m src.run --list

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

web-test:
	cd web && npm test

docker:
	docker build -t pharmatarget .
	docker run --rm -p 8000:8000 pharmatarget

test:
	$(PY) -m pytest tests/ -q

coverage:
	$(PY) -m pytest tests/ -q --cov=src --cov=api --cov-report=term-missing

lint:
	$(PY) -m ruff check src api tests

ci: lint test web-check web-test web-build

clean:
	rm -rf data/interim data/processed data/manifest.json
	rm -rf .pytest_cache .ruff_cache __pycache__

all: sample test lint
