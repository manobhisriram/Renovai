# LLMOps and observability

## Model routing

Tasks are classified `simple`, `medium` or `complex` by the router (`app/llm/router.py`) and mapped to model ids from settings (`LLM_MODEL_SIMPLE/MEDIUM/COMPLEX`). Defaults: Haiku 4.5 for extraction/classification, Sonnet for planning and negotiation, Opus for complex multi-room or conflicting-requirement jobs. A failing tier falls back to a cheaper one. **Model ids are configuration; verify them against the provider's models page before production.** They were not called live during the build.

Providers: `anthropic`, `openai`, `mock` (test double), plus any OpenAI-compatible local server via `OPENAI_BASE_URL`.

## Structured output and validation

Every structured call forces a `submit_<Schema>` tool, validates with Pydantic, and retries once with the validation error. Failures surface as run errors, never as silently invented data. Prices always come from the deterministic engine.

## Telemetry

Each LLM call, tool call, graph node and retrieval records: request id, run id, node, provider, model, tier, latency, input/output tokens, estimated cost, status and error class. Sinks (all optional except local):

| Sink | Enable |
|---|---|
| Database (`llm_calls`, `workflow_events`) | always; powers the Analytics page |
| Prometheus `/metrics` | always; protect with `METRICS_TOKEN` |
| Langfuse | `LANGFUSE_PUBLIC_KEY` + `LANGFUSE_SECRET_KEY` |
| OpenTelemetry | `OTEL_EXPORTER_OTLP_ENDPOINT` (install `requirements-otel.txt`) |

Metrics: `renovai_http_requests_total`, `renovai_http_request_seconds`, `renovai_llm_calls_total`, `renovai_llm_latency_seconds`, `renovai_llm_tokens_total`, `renovai_tool_calls_total`, `renovai_graph_node_seconds`, `renovai_rag_retrieval_seconds`, `renovai_quotes_created_total`, `renovai_approvals_total`, `renovai_crm_syncs_total`.

Logs are JSON with redaction of secrets, bearer tokens, API-key shapes, e-mails and phone numbers. Prompts/responses are not logged by default.

## Cost control

Cheapest adequate tier per task, bounded tool-loop (6 steps), bounded clarification rounds, token and cost recorded per call. Cost figures are estimates from configured per-million-token prices; update them when provider pricing changes.

## Evaluation

`backend/tests/evals/datasets` holds labelled cases. Run deterministic evals in CI; run live evals before changing prompts or models: `ANTHROPIC_API_KEY=... pytest -m live tests/evals`. Compare results across prompt/model versions before rollout.

## Prompt/versioning

Prompts live in code next to their schemas; quote versions are immutable and record the model, tier and assumptions used.
