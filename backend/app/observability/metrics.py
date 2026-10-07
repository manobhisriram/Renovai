"""Prometheus metrics. Exposed at /metrics (see app.main)."""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Histogram

REGISTRY = CollectorRegistry(auto_describe=True)

HTTP_REQUESTS = Counter("renovai_http_requests_total", "HTTP requests", ["method", "route", "status"], registry=REGISTRY)
HTTP_LATENCY = Histogram("renovai_http_request_seconds", "HTTP latency", ["method", "route"], registry=REGISTRY)
LLM_CALLS = Counter("renovai_llm_calls_total", "LLM calls", ["provider", "model", "tier", "status"], registry=REGISTRY)
LLM_LATENCY = Histogram("renovai_llm_latency_seconds", "LLM latency", ["model"], registry=REGISTRY,
                        buckets=(0.5, 1, 2, 5, 10, 20, 40, 80, 160))
LLM_TOKENS = Counter("renovai_llm_tokens_total", "LLM tokens", ["model", "direction"], registry=REGISTRY)
TOOL_CALLS = Counter("renovai_tool_calls_total", "Tool calls", ["tool", "status"], registry=REGISTRY)
NODE_LATENCY = Histogram("renovai_graph_node_seconds", "LangGraph node latency", ["node", "status"], registry=REGISTRY)
RAG_LATENCY = Histogram("renovai_rag_retrieval_seconds", "RAG retrieval latency", registry=REGISTRY)
QUOTES_CREATED = Counter("renovai_quotes_created_total", "Quote versions created", ["reason"], registry=REGISTRY)
APPROVALS = Counter("renovai_approvals_total", "Approval decisions", ["decision"], registry=REGISTRY)
CRM_SYNCS = Counter("renovai_crm_syncs_total", "CRM sync attempts", ["provider", "status"], registry=REGISTRY)
