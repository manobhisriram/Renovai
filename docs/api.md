# API

Base path `/api/v1`; interactive docs at `/docs` . Authentication: `Authorization: Bearer <JWT>` from `POST /api/v1/auth/login`. Roles: `admin`, `reviewer`, `sales`.

The complete, generated reference is in [api-endpoints.md](api-endpoints.md) and the machine-readable schema in [openapi.json](openapi.json). Regenerate both with `PYTHONPATH=backend python backend/scripts/export_docs.py`.

## Conventions

- Errors: `{"error": {"code": "...", "message": "...", "request_id": "..."}}`; every response carries `X-Request-ID`.
- Long-running workflow actions return immediately with a run id; poll `GET /projects/{id}/workflow` for status and events.
- Quotes are immutable versions; changes create a new version. Approval and CRM sync are idempotent.
- Rate limits apply to login and write-heavy endpoints (Redis if configured, otherwise in-process).
- Health: `GET /health` (liveness), `GET /ready` (dependencies), `/metrics` (Prometheus, token-protected).

## Typical flow

```
POST /auth/login → POST /projects → POST /projects/{id}/images → POST /projects/{id}/analyze
→ GET /projects/{id}/workflow (poll; answer questions via POST /projects/{id}/clarifications)
→ GET /projects/{id}/quotes → POST /approvals/{approval_id}/decision → CRM sync (automatic; retry via POST /crm/syncs/{sync_id}/retry)
Negotiation: POST /projects/{id}/messages or /quotes/revise
```
