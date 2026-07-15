.PHONY: install dev-install run test lint db-init seed migrate up down fmt \
        eval eval-injection eval-voice eval-all prove-restart ingest-policies web web-dev

VENV ?= .venv
PY := $(VENV)/bin/python
PYTHONPATH := src

install:
	uv venv --python 3.12 $(VENV)
	uv pip install --python $(PY) -r requirements.txt

dev-install: install
	uv pip install --python $(PY) -r requirements-dev.txt

run:  ## Run the API + console (in-memory checkpointer if DATABASE_URL unset)
	PYTHONPATH=$(PYTHONPATH) $(VENV)/bin/uvicorn app.main:app --reload --port 8000

web:  ## Build the React console -> web/dist (served by the API at /ui)
	cd web && npm install && npm run build

web-dev:  ## Frontend dev server with hot reload (proxies the API on :8000)
	cd web && npm run dev

test:
	PYTHONPATH=$(PYTHONPATH) $(PY) -m pytest -q

eval:  ## Routing precision/recall/false-escalation
	PYTHONPATH=$(PYTHONPATH) $(PY) -m evals.run_eval

eval-injection:  ## Prompt-injection robustness (attack-success-rate)
	PYTHONPATH=$(PYTHONPATH) $(PY) -m evals.run_injection_eval

eval-voice:  ## Voice surface: identity gate + no unapproved executions + injection
	PYTHONPATH=$(PYTHONPATH) $(PY) -m evals.run_voice_eval

eval-all: eval eval-injection eval-voice  ## Every quotable number

prove-restart:  ## Prove pause/resume across a REAL process restart (SQLite, no Docker)
	@rm -f data/restart-demo.sqlite
	CHECKPOINT_BACKEND=sqlite SQLITE_PATH=data/restart-demo.sqlite PYTHONPATH=$(PYTHONPATH) $(PY) scripts/prove_restart.py pause
	CHECKPOINT_BACKEND=sqlite SQLITE_PATH=data/restart-demo.sqlite PYTHONPATH=$(PYTHONPATH) $(PY) scripts/prove_restart.py resume
	@rm -f data/restart-demo.sqlite

ingest-policies:  ## Embed policy docs into pgvector (needs DATABASE_URL, RETRIEVER=vector)
	PYTHONPATH=$(PYTHONPATH) $(PY) scripts/ingest_policies.py

db-init:  ## Create pgvector extension + tables (dev fast path)
	PYTHONPATH=$(PYTHONPATH) $(PY) scripts/init_db.py

seed:
	PYTHONPATH=$(PYTHONPATH) $(PY) scripts/seed.py

migrate:  ## Autogenerate a migration: make migrate m="message"
	$(VENV)/bin/alembic revision --autogenerate -m "$(m)"

up:  ## docker compose up (Postgres + API)
	docker compose up --build

down:
	docker compose down
