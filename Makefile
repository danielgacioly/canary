.PHONY: setup dev api web test build serve dataset

# The virtualenv keeps its programs in .venv/bin on macOS and Linux and in .venv/Scripts on Windows.
VENV_BIN := .venv/$(if $(filter Windows_NT,$(OS)),Scripts,bin)
PYTHON ?= python3

setup:            ## install backend and frontend dependencies
	cd backend && $(PYTHON) -m venv .venv && $(VENV_BIN)/pip install -r requirements.txt
	cd frontend && npm install

api:              ## API on http://localhost:8000 (docs at /docs)
	cd backend && $(VENV_BIN)/uvicorn canary.main:app --reload --port 8000

web:              ## web app on http://localhost:5173 (proxies /api to :8000)
	cd frontend && npm run dev

dev:              ## API and web app together; Ctrl+C stops both
	$(MAKE) -j2 api web

test:             ## backend tests + frontend type check
	cd backend && $(VENV_BIN)/python -m pytest -q
	cd frontend && npm run typecheck

dataset:          ## rebuild data/observations.csv and data/DATASET.md from data/recipes.json and data/real/
	$(PYTHON) data/generate_dataset.py

build:            ## production build of the web app into frontend/dist
	cd frontend && npm run build

serve: build      ## one process serves API and built app on http://localhost:8000
	cd backend && $(VENV_BIN)/uvicorn canary.main:app --port 8000
