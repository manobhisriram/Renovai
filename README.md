# RenovAI

**An agentic AI platform that turns a client's photos and a plain-language request into a defensible, versioned renovation quote, which a human approves before anything reaches the client or the CRM.**

![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)
![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)
![Node 22](https://img.shields.io/badge/node-22-green.svg)

Built by **Manobhi Sriram** as a reference implementation of a production-style agentic AI system: LangGraph orchestration, multimodal vision, RAG on Qdrant, tool use, tiered model routing, deterministic pricing, human-in-the-loop approval, observability and cloud deployment.

<!-- Add screenshots here, e.g.:
![Dashboard](docs/images/dashboard.png)
![Workflow](docs/images/workflow.png)
![Quote](docs/images/quote.png)
-->

> **About the data.** All catalog prices, past projects and policies shipped with this repo are **sample data** (`is_sample=true`, labelled in the UI). Replace them with your own before quoting real clients. The built-in **mock AI** exists for development and CI; it cannot read images and must not be used for real quotes.

---

## Contents

1. [What it does](#1-what-it-does)
2. [Quick start (2 minutes, no API key)](#2-quick-start-2-minutes-no-api-key)
3. [Architecture](#3-architecture)
4. [The AI system](#4-the-ai-system)
5. [Local setup](#5-local-setup)
6. [Docker setup](#6-docker-setup)
7. [Environment variables](#7-environment-variables)
8. [Database migrations and seed data](#8-database-migrations-and-seed-data)
9. [Testing](#9-testing)
10. [Deployment (AWS / Terraform)](#10-deployment-aws--terraform)
11. [Security](#11-security)
12. [Observability](#12-observability)
13. [Project structure](#13-project-structure)
14. [Troubleshooting](#14-troubleshooting)
15. [Limitations](#15-limitations)
16. [Documentation index](#16-documentation-index)
17. [License](#17-license)

---

## 1. What it does

1. A staff member creates a project: client details, a free-text request and optional photos.
2. The workflow reads the photos (computer-vision measurements plus a multimodal model), extracts structured requirements and classifies the job into one of 7 categories: general, kitchen, bathroom, living/bedroom, flooring/wall, outdoor/landscaping, smart-home.
3. If critical details are missing (for example floor area) it asks the client and **pauses**. The reply resumes the same run. After a bounded number of rounds it proceeds with explicit, flagged assumptions.
4. It retrieves similar past projects, quotes, policies and (for returning clients) preference profiles from Qdrant.
5. A tool-using planner chooses materials and quantities. **A deterministic engine prices them**: the model never invents prices. It produces budget, standard and premium options plus a programme estimate.
6. Validation flags risks and decides whether a human must approve. A reviewer approves or rejects; only then is the lead written to the CRM, idempotently.
7. If the client says "too expensive", a budget fitter downgrades materials and drops optional lines step by step, and records every trade-off as a new immutable quote version.

The UI separates what was **detected**, **estimated**, **user-provided** and **unknown**, and never shows model reasoning.

## 2. Quick start (2 minutes, no API key)

Requirements: Python 3.12, Node 22.

```bash
git clone https://github.com/manobhisriram/Renovai.git
cd Renovai
make setup                                  # venv + backend deps + frontend deps
cp .env.example backend/.env
```

Edit `backend/.env` and set at minimum:

```
LLM_PROVIDER=mock
SEED_ADMIN_PASSWORD=choose-a-strong-password
```

```bash
make backend-dev                            # migrate, seed sample data, API on :8000
make frontend-dev                           # UI on :5173 (proxies /api to :8000)
```

Open http://localhost:5173 and sign in as `admin@renovai.local` with the password you set. For real AI, see [Environment variables](#7-environment-variables).

## 3. Architecture

A modular monolith: FastAPI and LangGraph in one process, with PostgreSQL (state), Qdrant (vectors), Redis (rate limiting), S3-compatible storage (photos) and a React SPA behind nginx.

```
React UI ──► FastAPI ──► LangGraph workflow ──► LLM provider (Anthropic / OpenAI / mock)
                │              │  ├─► Qdrant (RAG)
                │              │  ├─► Tools (pricing, catalog, calculators)
                │              │  └─► Vision (CV + multimodal)
                ├─► PostgreSQL (projects, quotes, runs, audit)
                ├─► S3-compatible storage (photos)
                └─► CRM provider (internal / HubSpot / Google Sheets)
```

Details: [docs/architecture.md](docs/architecture.md).

## 4. The AI system

| Capability | How it works |
|---|---|
| **Orchestration** | LangGraph `StateGraph` with conditional routing, a bounded clarification loop, checkpointed persistence and human-approval interrupts. One planner node per category, generated from a registry, so new categories are extensible. The diagram is generated: [docs/workflow-graph.md](docs/workflow-graph.md). |
| **Model routing** | Tasks are classified simple / medium / complex and routed to a model tier set in config, with fallback to a cheaper tier on failure. |
| **Structured output** | A forced tool call plus Pydantic validation, with one validation-retry. Failures surface as errors, never as invented data. |
| **RAG** | Qdrant with metadata filters, chunking, and reranking (vector + lexical + metadata boosts). Retrieved text is treated as untrusted. |
| **Tools** | Typed, validated, logged, time-limited. The model gets read-only tools; write actions are application-only. The model never executes arbitrary code. |
| **Pricing** | Decimal arithmetic. `line = (qty x unit_price + qty x labour_hrs x rate x complexity) x regional`, plus logistics, contingency and tax. |
| **Negotiation** | A stateful budget fitter that creates new immutable quote versions. |
| **Vision** | Image validation and CV measurements plus a multimodal model. Dimensions from photos are estimates, clamped and labelled, and never used as the area without confirmation. |
| **Human in the loop** | Configurable approval thresholds. The CRM is written only after approval. |
| **Prompt-injection defence** | Untrusted-content delimiters, a scanner, and flagged retrieved chunks excluded from context. |

Default model tiers (configurable, verify against your provider's models page):

| Tier | Used for | Default |
|---|---|---|
| simple | extraction, classification | `claude-haiku-4-5-20251001` |
| medium | planning, negotiation | `claude-sonnet-5-5` |
| complex | multi-room or conflicting-requirement jobs | `claude-opus-5-5` |

Details: [docs/ai-architecture.md](docs/ai-architecture.md), [docs/rag.md](docs/rag.md), [docs/llmops.md](docs/llmops.md).

## 5. Local setup

See the [quick start](#2-quick-start-2-minutes-no-api-key). For real AI set in `backend/.env`:

```
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=your-key-here
```

Never commit `.env`. It is git-ignored.

## 6. Docker setup

```bash
cp .env.example .env        # set POSTGRES_PASSWORD, SECRET_KEY (>=32 chars), SEED_ADMIN_PASSWORD, and LLM settings
docker compose up --build
docker compose run --rm backend python -m scripts.seed
```

UI: http://localhost:8080. Postgres, Redis and Qdrant sit on an internal network and are not published.
Hardened override: `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d`.

## 7. Environment variables

Every variable is documented in [`.env.example`](.env.example). A test fails if a setting is added to the code without being documented there.

Required in production: `SECRET_KEY` (>=32 chars), `DATABASE_URL` (PostgreSQL), `QDRANT_URL`, credentials for your chosen LLM provider, and CRM or S3 credentials if used. In production the app **refuses to start** with unsafe or missing configuration. In development it starts, and `/ready` plus the Settings page show what is missing.

Credentials come only from environment variables and are never logged.

## 8. Database migrations and seed data

```bash
cd backend
alembic upgrade head                        # schema (a test fails if models and migration drift)
python -m scripts.seed                      # sample catalog, regions, labour rates, leads, 15 knowledge docs, admin user
python -m scripts.seed --reset-knowledge    # rebuild the Qdrant collection
```

## 9. Testing

```bash
make check                                  # ruff, mypy, eslint, tsc, all tests, repo checks
cd backend && python -m pytest -q           # 200 tests
cd frontend && npm test                     # 23 tests
```

Live-model evals are opt-in: `ANTHROPIC_API_KEY=... pytest -m live tests/evals`. Details: [docs/testing.md](docs/testing.md).

## 10. Deployment (AWS / Terraform)

`infra/terraform` provisions a VPC, ECS Fargate services behind an HTTPS ALB, RDS PostgreSQL, ElastiCache Redis, a private S3 bucket, ECR, Secrets Manager and CloudWatch logs. Databases and caches are in private subnets only.

```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars
terraform init && terraform validate && terraform plan && terraform apply
```

Full guide and first-deploy checklist: [docs/deployment.md](docs/deployment.md).

## 11. Security

Secrets only from the environment; scrypt password hashing; JWT with expiry; role-based access (admin, reviewer, sales); validated uploads (decoded, allow-listed, size-limited, EXIF stripped, traversal-guarded); structured error responses; prompt-injection defences; secret scanning in CI. Full list: [docs/security.md](docs/security.md).

## 12. Observability

Structured JSON logs with redaction, request IDs, Prometheus metrics at `/metrics`, per-call model, token, latency and cost tracking, and optional Langfuse and OpenTelemetry export. Details: [docs/llmops.md](docs/llmops.md).

## 13. Project structure

```
backend/      FastAPI app, LangGraph workflow, agents, pricing, RAG, vision, CRM, tests
frontend/     React 18 + Vite + TypeScript console, tests, nginx config
infra/        Terraform for AWS
docs/         Architecture, AI, API, RAG, security, testing, LLMOps, deployment
scripts/      Repo consistency checks
.github/      CI workflow (lint, types, tests, build, Docker, scanning)
```

## 14. Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| Backend exits with "Invalid production configuration" | `APP_ENV=production` with a weak `SECRET_KEY`, SQLite, `*` CORS or mock AI. Fix the listed items. |
| "ANTHROPIC_API_KEY is not set" | Set the key, or use `LLM_PROVIDER=mock` for a demo. |
| Run fails with HTTP 400/404 from the provider | A model ID in `LLM_MODEL_*` is wrong or not enabled for your key. |
| "collection ... has 384-dim vectors" | You changed the embedder. Use a new `QDRANT_COLLECTION` or run `python -m scripts.seed --reset-knowledge`. |
| Quote has no evidence | Knowledge base empty or Qdrant down. Run the seed script and check `/ready`. |
| CRM sync "failed" | The quote stays approved. Fix credentials, then use **Retry sync** (idempotent). |
| `database is locked` | SQLite is for single-user development. Use PostgreSQL for anything shared. |
| "Cannot reach the server" in the UI | Backend not running, or the proxy/`VITE_API_BASE` points elsewhere. |

## 15. Limitations

- **Staff console, not a public portal.** Clients do not log in; staff relay their messages.
- **Single-tenant, role-based access.** No per-project ACLs, MFA or token revocation list.
- **Workflow runs execute in the API process** (background threads). State is checkpointed, but heavy load should move to a worker queue.
- **Sample pricing.** Quote quality depends on your catalog and past-project data, not on the model alone.
- **Vision cannot measure.** Photo dimensions are labelled estimates.
- **Lexical embeddings by default.** Set `EMBEDDING_PROVIDER=sentence_transformers` (build with `INSTALL_ML=true`) for semantic retrieval.
- Photos and request text are sent to your LLM provider; check their data-processing terms for your clients' data.

## 16. Documentation index

[Architecture](docs/architecture.md) · [AI architecture](docs/ai-architecture.md) · [RAG](docs/rag.md) · [API](docs/api.md) · [Endpoints](docs/api-endpoints.md) · [Workflow graph](docs/workflow-graph.md) · [Security](docs/security.md) · [Testing](docs/testing.md) · [LLMOps](docs/llmops.md) · [Deployment](docs/deployment.md)

## 17. License

MIT, see [LICENSE](LICENSE). Copyright (c) 2026 Manobhi Sriram.
