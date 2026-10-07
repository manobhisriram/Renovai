.PHONY: help setup backend-dev frontend-dev test lint typecheck check up down seed verify
help:            ## list targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-14s %s\n", $$1, $$2}'
setup:           ## create venv + install backend and frontend deps
	python3 -m venv .venv && . .venv/bin/activate && pip install -r backend/requirements-dev.txt
	cd frontend && npm ci
backend-dev:     ## run migrations, seed sample data and start the API on :8000 (uses backend/.env)
	cd backend && ../.venv/bin/alembic upgrade head && ../.venv/bin/python -m scripts.seed && ../.venv/bin/uvicorn app.main:app_factory --factory --reload --port 8000
frontend-dev:    ## start the UI on :5173 (proxies /api to :8000)
	cd frontend && npm run dev
test:            ## backend + frontend tests
	cd backend && ../.venv/bin/python -m pytest -q
	cd frontend && npm test
lint:            ## ruff + eslint
	cd backend && ../.venv/bin/ruff check .
	cd frontend && npm run lint
typecheck:       ## mypy + tsc
	cd backend && ../.venv/bin/mypy app
	cd frontend && npm run typecheck
check: lint typecheck test verify  ## everything CI runs (except Docker builds)
verify:          ## repo consistency checks (Docker COPY paths, compose, workflows, env docs)
	.venv/bin/python scripts/verify_repo.py
up:              ## full stack in Docker
	docker compose up --build
down:
	docker compose down
seed:            ## seed the Docker stack with sample data
	docker compose run --rm backend python -m scripts.seed
