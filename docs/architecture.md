# Architecture

```
Browser (React SPA) ── nginx ──► FastAPI ─┬─► LangGraph workflow ─► LLM provider (Anthropic / OpenAI-compatible)
                                          ├─► PostgreSQL   application state, quotes, audit, LLM call log, graph checkpoints
                                          ├─► Qdrant       knowledge base vectors
                                          ├─► Redis        shared rate-limit counters (optional; in-process fallback)
                                          ├─► Object store photos and renders (local disk or S3-compatible)
                                          └─► CRM          internal (default) | HubSpot | Google Sheets
```

## Layers (backend/app)

| Package | Responsibility |
|---|---|
| `api/` | HTTP routers (auth, projects, workflow, approvals, rag, crm, catalog, visualization, analytics) and health |
| `graph/` | LangGraph state, instrumented nodes, topology (`builder.py`), run lifecycle and durable checkpointing (`runtime.py`) |
| `agents/` | Prompted, schema-validated LLM tasks: requirements, planning (classification, clarification, scope), quoting, chat |
| `llm/` | Provider abstraction, model router, structured-output and tool-loop client, prompt-injection defences, test double |
| `tools/` | Controlled tool execution: typed args, allow-lists, timeouts; model-callable (read-only) vs application-only (side effects) |
| `pricing/` | Catalog snapshot, deterministic pricing, timeline, budget fitter |
| `categories/` | Registry of project categories (data, not code) |
| `rag/` | Embeddings, chunking, Qdrant store, ingestion, reranked retrieval, untrusted-context construction |
| `vision/` | Secure image intake, deterministic CV measurements, multimodal analysis and honesty clamps |
| `crm/` | `CRMProvider` interface and providers |
| `services/` | Domain services (quotes, approvals, idempotent CRM sync, chat dispatcher, audit, seeding) and the composition root |
| `observability/` | JSON logging with redaction, request context, Prometheus, LLM telemetry sinks |
| `storage/`, `viz/`, `database/`, `auth/`, `config/`, `utils/` | Adapters and cross-cutting code |

Dependencies point inward: routers call services and the workflow; the workflow calls agents, pricing, RAG and tools; nothing in `pricing/` or `categories/` knows about the LLM.

## Key decisions

1. **AI reasons, code calculates.** The model proposes materials/quantities; every currency figure comes from `pricing/engine.py` (Decimal, reconciling to the cent). A narrative that mentions an amount not produced by the engine is replaced and flagged.
2. **Human-in-the-loop by default.** Quotes need approval unless policy thresholds say otherwise (`APPROVAL_REQUIRE_ALWAYS=true`). The CRM is written only after approval. Decision: the CRM *lookup* happens early (to recognise returning clients); the *write* happens after approval.
3. **Immutable quote versions.** Revisions create a new version; earlier versions are never edited (a test asserts this).
4. **One graph, three entry modes.** `initial`, `replan` and `revise` share nodes and a per-project checkpoint thread, so negotiation continues from stored state. If the checkpoint is lost, state is rehydrated from the latest stored quote.
5. **Failures are contained.** A failed step ends the run with an error and never corrupts stored state; optional dependencies degrade (no vector DB → quote without evidence, flagged; CRM down → quote stays approved, sync is retryable).
6. **Nothing holds a DB transaction across an external call** (see `services/crm_sync.py`).
7. **Categories are data.** Adding a vertical means registering a `CategoryProfile` and seeding its materials; the graph generates a planner node for it automatically.
8. **Run model.** Runs execute in FastAPI background threads; the UI polls `/workflow`. Stale `running` rows are failed at startup.
