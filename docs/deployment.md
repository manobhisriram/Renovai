# Deployment

## Docker Compose (single host)

```bash
cp .env.example .env     # set POSTGRES_PASSWORD, SECRET_KEY (>=32 chars), SEED_ADMIN_PASSWORD, LLM_PROVIDER + key
docker compose up --build -d
docker compose run --rm backend python -m scripts.seed
```

Postgres, Redis and Qdrant sit on an `internal: true` network with no published ports; only the frontend (nginx, port 8080) is on the edge network. Production override: `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d` (read-only filesystem, dropped capabilities, no-new-privileges). Put a TLS terminator in front.

## AWS (Terraform)

`infra/terraform` provisions a VPC, ECS Fargate services (backend, frontend) behind an HTTPS ALB, RDS PostgreSQL, ElastiCache Redis, S3 (private, encrypted), ECR, Secrets Manager and CloudWatch logs. Databases and caches are in private subnets and reachable only from the service security group.

```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars   # region, domain, ACM cert ARN, image URIs
terraform init && terraform validate && terraform plan
terraform apply
```

Build and push images to the ECR repositories first, then set `backend_image` / `frontend_image`. Qdrant: point `qdrant_url` at Qdrant Cloud or your own deployment (secret API key goes in Secrets Manager). Set secret values (Anthropic key, CRM tokens) in Secrets Manager out of band; they never go in `.tf` files or state defaults.

## First-deploy verification checklist

1. `GET /health` returns ok; `GET /ready` shows database, vector store and storage healthy.
2. `GET /api/v1/system/config` lists no configuration problems.
3. Log in with the seeded admin; change the password.
4. Seed (or replace) the catalog and knowledge base; confirm retrieval returns evidence in a project run.
5. Run one project end to end with the real provider; check Analytics shows model, tokens and cost, and confirm the model ids are valid.
6. Approve a quote; confirm the CRM record, then retry sync to confirm idempotency.
7. Upload a photo and confirm it is only reachable through the authenticated endpoint.
8. Confirm Postgres, Redis and Qdrant are not reachable from the internet.
9. Scrape `/metrics` with the token; confirm logs contain no secrets.

## CRM verification

Default provider `internal` stores leads in the database. For HubSpot set `CRM_PROVIDER=hubspot` and `HUBSPOT_ACCESS_TOKEN` (private-app token with contacts/deals scopes). The HubSpot adapter is written against the public API and tested only with fake HTTP; verify with a sandbox account first. Sync is idempotent on `project_id:vN`.

## Rollbacks and migrations

`RUN_MIGRATIONS=true` runs `alembic upgrade head` at container start. Take a database snapshot before upgrading; downgrade with `alembic downgrade -1`.
