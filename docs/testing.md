# Testing

## Layout

| Suite | Location | What it covers |
|---|---|---|
| Unit | `backend/tests/unit` | Pricing engine (Decimal maths, rounding, budget fitter, timeline), text parsing, model router, config validation, prompt-injection scanner, retries/circuit breaker/rate limit, log redaction and auth, LLM provider adapters (against fakes), tool registry boundary, image validation and storage guards, AI output validators, `.env.example` completeness |
| Integration | `backend/tests/integration` | Full HTTP flow with the mock AI, LangGraph run/interrupt/resume/replan/revise, RAG on an in-memory Qdrant, migrations vs. models drift and seeding, CRM providers (fake HTTP), API security (roles, uploads, traversal), regression tests for production gaps |
| Evals | `backend/tests/evals` | Dataset-driven checks of extraction, routing, pricing invariants and injection resistance; deterministic by default; live-model runs are opt-in (`pytest -m live`, needs `ANTHROPIC_API_KEY`) |
| Frontend | `frontend/src/**/*.test.tsx` | API client, stores, hooks, key components and pages (vitest + Testing Library) |
| Repo checks | `scripts/verify_repo.py` | Dockerfile COPY paths, compose wiring, CI references, Terraform syntax/reference consistency, secret patterns, `.gitignore` coverage |

## Commands

```bash
make check                                   # ruff, mypy, eslint, tsc, all tests, repo checks
cd backend && python -m pytest -q --cov=app  # backend
cd frontend && npm test                      # frontend
python scripts/verify_repo.py                # repo consistency
```

## What was and was not verified

Executed by the automated build checks (mock AI, SQLite, in-memory Qdrant):

- Backend: 200 tests passed; `ruff check` clean; `mypy app` clean (106 files).
- Frontend: 23 tests passed; `tsc --noEmit`, `eslint --max-warnings 0` and `vite build` clean.
- Alembic `upgrade head` against SQLite, seeding, and the full workflow driven over a real uvicorn server with the mock AI.
- `scripts/export_docs.py` (OpenAPI, endpoint list and graph diagram are generated from the running code).

**Not executed** (written to spec, unproven until you run them): live Anthropic/OpenAI calls, live HubSpot/Google Sheets/S3/Langfuse/OTel, PostgreSQL migrations, real Qdrant server, sentence-transformers and YOLO paths, browser rendering, Terraform `validate/plan/apply`, and live evals. Docker image builds and `docker compose up` were not run by the automated build checks; the maintainer ran the stack manually, and CI builds the images on every push.

## Writing new tests

Use the `client` / `settings` fixtures in `tests/conftest.py` (mock provider, temp SQLite, temp upload dir). Never call a real provider from a default test; mark those `@pytest.mark.live`.
