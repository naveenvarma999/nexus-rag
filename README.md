# Nexus RAG — Version 2

A portable, full-stack document Q&A application with email-verified accounts, password recovery, Google sign-in, database-backed authentication and private search history. The interface focuses on asking questions, managing documents and revisiting answers. A subtle CSS 3D animation appears on the sign-in screen; there is no architecture dashboard in the customer UI.

**Status:** application code and AWS deployment configuration are included. This project has not been deployed to your AWS account. Customer email delivery, Google sign-in and AI calls require the account configuration below. This is a security-conscious implementation to validate and operate, not a claim of perfect security, unlimited scale or production certification. It is a standalone AWS version, not an export of Floot's proprietary runtime.

## New in version 2

Continuous-refill distributed token buckets; request-idle session expiry; five-session cap; Account security screen; remote logout; current-password verification for password changes; JWT signing-key rotation; PostgreSQL row-level isolation; separate worker DB roles; leased/fenced background jobs with bounded retries; a shared provider circuit breaker; forward schema migration; WAF configuration; and expanded verification.

For an existing installation, read [docs/UPGRADE-V2.md](docs/UPGRADE-V2.md) **before** starting the new image. Version 2 requires a migration and a maintenance window. The migration intentionally signs out version 1 sessions.

## Run locally

Install Docker with Compose and Python 3.12 or later for the setup helper.

```bash
python scripts/setup.py
docker compose up --build
```

Open **http://localhost:8000**. The first startup runs the schema migration before the API and workers start. Open **http://localhost:8025** for the development email inbox. Signup and password-reset codes appear there; local SMTP does not deliver to real customers. Use `localhost` consistently, because the origin check intentionally rejects `127.0.0.1` as a different origin.

For real document embedding and answers, edit `.env` with AWS credentials for local development and a Bedrock Converse model or inference-profile ID enabled in your region. ECS uses IAM task roles instead of static AWS keys. Authentication works without an AI model. Document ingestion will show a failed status if the embedding provider is unavailable; remove and re-upload after fixing configuration.

To stop containers while keeping your database:

```bash
docker compose down
```

Do not use `down -v` unless you intend to delete all local data.

## What is implemented

| Capability | Behavior |
|---|---|
| Create account | Six-digit cryptographically random email code; 10-minute expiry; account is created only after verification |
| Passwords | Argon2id with per-password salts, 19 MiB memory, two iterations, one lane; 12–128 character passwords |
| Login lockout | Five consecutive incorrect password attempts lock password sign-in for one hour; database row locking coordinates replicas |
| OTP lockout | Five incorrect codes lock that email/purpose for one hour, including across resends |
| Forgot password | Generic response, expiring one-use email code, password confirmation in UI, all existing sessions revoked on reset |
| JWT | 15-minute signed access token in an HttpOnly cookie; issuer, audience, signature and required claims checked |
| Refresh | Opaque random token, only an HMAC digest stored; rotation on every refresh; replay revokes the entire session family |
| Logout | Revokes the server-side session and blacklists its issued access-token IDs; copied tokens stop working |
| Sessions | 30-day absolute lifetime, 30-minute request inactivity limit, five-session cap, user-visible revocation controls |
| Google | Authorization code flow with state, nonce, PKCE and signature-verified Google ID token; no unsafe automatic linking to an existing password account |
| Request security | Same-origin mutations, CSRF token bound to session, strict CSP, production secure cookies, bounded request body |
| Email | Encrypted transactional database outbox; SES worker with bounded retries; no public endpoint exposes OTPs |
| Rate limiting | Shared PostgreSQL token buckets with continuous refill plus account locks; `429` and `Retry-After` |
| RAG | Durable background text/Markdown ingestion; Bedrock Titan embeddings; PostgreSQL pgvector retrieval; Bedrock Converse answers with source excerpts |
| Private data | Ownership filters plus forced PostgreSQL RLS; identity set per transaction; separate index/mail DB roles |
| History | Latest 100 saved questions and answers shown; user can clear all history |
| AWS | Terraform for HTTP API Gateway → private ALB → ECS Fargate; RDS PostgreSQL Multi-AZ; IAM, Secrets Manager, WAF, autoscaling and CloudWatch |

Read [docs/AWS.md](docs/AWS.md) for cloud deployment and [docs/DESIGN.md](docs/DESIGN.md) for the implementation decisions, limits and research references. These are developer documents, not customer UI screens.

## Project folders

- `frontend/`: responsive HTML, CSS and browser JavaScript. No frontend build step or token storage in localStorage.
- `backend/app/`: FastAPI application, authentication, provider integrations, ingestion and email workers, migration and cleanup commands.
- `backend/tests/`: authentication, isolation and PostgreSQL concurrency tests.
- `infra/`: AWS Terraform configuration and example values.
- `.github/workflows/`: CI using an isolated PostgreSQL/pgvector test database.
- `docs/`: AWS setup, security/architecture rationale and verification results.

## Tests

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r backend/requirements.txt
PYTHONPATH=backend pytest backend/tests -q
node --check frontend/app.js
```

The default suite uses a temporary SQLite database and mocked AI provider calls; it does not send external emails. PostgreSQL-only concurrency tests are skipped in that mode. To run the complete suite, create an isolated PostgreSQL database **named `nexus_test`** with pgvector available and set:

```bash
TEST_DATABASE_URL='postgresql+psycopg://USER:PASSWORD@HOST:5432/nexus_test' \
  PYTHONPATH=backend pytest backend/tests -q
```

Tests drop/recreate tables in the test database. Never point them at an application database. CI runs against an isolated service. See [docs/VERIFICATION.md](docs/VERIFICATION.md) for checks actually completed here.

## Daily maintenance

Run `python -m app.cleanup` once a day using an ECS task override or a scheduled container job. It removes expired authentication records and rate buckets, processed email payload records, expired work leases and audit events older than 90 days. It does not remove customer documents/history. Monitor pending and failed email/indexing jobs before deleting processed outbox records. Auth gate rows persist; set an account-erasure/retention policy before a public launch.

The migration runner creates the schema and vector index and applies the recorded version 2 upgrade when required. Future schema changes need additional explicit migrations. Back up first and run migrations as a separate task, never on every API startup.
