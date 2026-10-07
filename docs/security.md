# Security

## Controls implemented

| Area | Control |
|---|---|
| Secrets | Only from environment (typed `Settings`); `.env` git-ignored; `.env.example` has no values; log redaction of configured secrets, API-key shapes, bearer tokens, e-mails (masked) and phone numbers; repo secret-pattern scan in `scripts/verify_repo.py` and gitleaks in CI |
| Startup safety | Production refuses to start with a default/short `SECRET_KEY`, `*` CORS, SQLite, or mock AI |
| AuthN | scrypt password hashes; HS256 JWT with expiry; inactive users rejected on every request; generic login errors and a dummy hash for unknown users; login rate-limited |
| AuthZ | Roles `admin / reviewer / sales`. Approvals: reviewer/admin. Knowledge base writes, price edits, user creation, audit log: admin. Self-registration cannot choose a role and is closed once a user exists |
| Input | Pydantic validation on every body; parameterised SQL via SQLAlchemy; bounded reads for uploads; structured error responses |
| Uploads | Decoded (not trusted by header), format allow-list, size/pixel limits, EXIF stripped by re-encoding, server-generated storage keys, display filename sanitised, duplicate-content refusal, per-project cap, path-traversal guards on both storage backends (tested), images served only through an authenticated endpoint with `nosniff` |
| Transport/headers | CORS limited to configured origins; `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`, `Permissions-Policy`; nginx CSP; TLS at the load balancer (Terraform) |
| Rate limiting | Fixed-window per IP; Redis-backed when configured, in-process fallback; stricter on auth and renders |
| AI | Untrusted-content delimiters, injection scanner, read-only model tools, application-only write tools, schema-validated outputs, deterministic money, forced human approval on suspicion (see ai-architecture.md) |
| SSRF | The server only calls base URLs from configuration; no endpoint fetches a user-supplied URL |
| Network (Terraform/compose) | DB, Redis and Qdrant on private networks; DB/Redis security groups accept only the backend SG; S3 public access blocked, TLS-only, encrypted; ECS task role limited to the uploads bucket; ALB exposes only `/api/*` and the SPA (`/health`, `/ready`, `/metrics`, `/docs` are not routable) |
| Containers | Non-root users, minimal base images, health checks, `no-new-privileges`, dropped capabilities and read-only filesystems in the production compose override |
| Audit | `audit_events` for logins, project/quote/approval/CRM/RAG/admin actions with request ids; LLM calls logged without prompts |

## Known limitations (be aware before going live)

- No MFA, no refresh tokens, no server-side token revocation; the access token is held in `sessionStorage` (XSS-readable; the CSP is the mitigation).
- Authorisation is role-based, not per-project/tenant: every staff user can see every project.
- The injection scanner is heuristic. Photos could contain text instructions; vision output is schema-validated and cannot trigger tools, but it is not scanned.
- Uploaded files are validated as images but not malware-scanned. Knowledge-base PDFs are parsed with `pypdf`.
- `FORWARDED_ALLOW_IPS=*` in compose is safe only because the backend port is not published; set it to your proxy CIDR elsewhere.
- Rate limits are per client IP and rely on a trustworthy `X-Forwarded-For` from your proxy.
- Photos and request text leave your infrastructure for the LLM provider; review their data terms and your clients' consent.
- Dependency and image scanning run in CI (`pip-audit`, `npm audit`, Trivy); results from this repository's CI were not available at packaging time.
