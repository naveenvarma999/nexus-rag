# Nexus RAG

**Ask questions about your own documents and get answers that cite their sources.**

Nexus RAG is a retrieval-augmented generation (RAG) app. You add documents, it splits and embeds them in the background, and when you ask a question it retrieves the most relevant passages and has an LLM answer **only from those passages**, with numbered citations. Every user's documents and history are private, enforced inside the database itself.

**Live demo:** https://nexus-rag-naveen.floot.app — a hosted prototype built and published on Floot.

**This repository** is my portable re-implementation of the same product in FastAPI, PostgreSQL/pgvector and AWS Bedrock. It runs locally with Docker Compose. Terraform for AWS (ECS Fargate, RDS) is included as a deployment design and has not been applied; my AWS deployments are [FraudGuard](https://github.com/naveenvarma999/fraudguard) and [Threadline](https://github.com/naveenvarma999/threadline).

---

## How it works

```mermaid
flowchart LR
    U[User] -->|upload text| API[FastAPI]
    API -->|"job: pending"| DB[(PostgreSQL + pgvector)]
    W[Indexing worker] -->|claim job with lease| DB
    W -->|"chunk: 1,200 chars, 200 overlap"| E[Bedrock Titan embeddings v2]
    E -->|vectors| DB
    U -->|question| API
    API -->|embed question| E
    API -->|"top-5 cosine search, own docs only"| DB
    API -->|"question + 5 excerpts"| LLM[Bedrock Converse]
    LLM -->|"answer with cited sources"| U
```

1. **Ingest:** a document is saved with status `pending` and returned immediately (HTTP 202). Duplicate documents are rejected by content hash.
2. **Index:** a background worker claims the job with a time-limited lease, splits the text into overlapping chunks, embeds each chunk with Titan Text Embeddings v2 and stores the vectors in pgvector. A crashed worker's lease expires and another worker takes over; retries are bounded.
3. **Retrieve:** the question is embedded and the 5 nearest chunks by cosine distance are fetched, filtered to the asking user's ready documents.
4. **Generate:** the excerpts are sent to a Bedrock chat model at temperature 0.1 with a grounding prompt: answer only from the excerpts, say so when the answer is absent, cite every claim, and treat document text as data, never as instructions (a defence against prompt injection hidden in documents).
5. **Remember:** the question, answer and sources are saved to the user's private history.

## Engineering highlights

| Area | What I built |
|---|---|
| **Private retrieval** | Ownership filters **plus** forced PostgreSQL row-level security; the user identity is set per transaction, and the indexing and mail workers use separate, restricted database roles |
| **Reliable background jobs** | Leased, fenced indexing jobs with heartbeats and bounded retries; a shared circuit breaker stops hammering the AI provider when it fails |
| **Capacity control** | Shared token-bucket rate limits in PostgreSQL (per user and global) and a cap on concurrent RAG requests; overload returns `429` with `Retry-After` |
| **Authentication** | Email-verified sign-up, Argon2id password hashing, 15-minute JWTs in HttpOnly cookies, rotating refresh tokens where a replayed token revokes the whole session family, Google sign-in with PKCE |
| **Request security** | Same-origin checks, CSRF tokens bound to the session, strict Content-Security-Policy, bounded request bodies |
| **Testing & CI** | 29 automated tests covering auth, data isolation, job leasing and rate limits; GitHub Actions runs them against a PostgreSQL/pgvector service, plus dependency auditing |
| **Infrastructure as code** | Terraform for API Gateway → private ALB → ECS Fargate, RDS PostgreSQL Multi-AZ, Secrets Manager, WAF, autoscaling and CloudWatch |

## Tech stack

**Backend:** Python, FastAPI, SQLAlchemy · **Vector store:** PostgreSQL + pgvector · **AI:** AWS Bedrock (Titan Text Embeddings v2, Converse API) · **Frontend:** HTML, CSS, JavaScript (no build step) · **Ops:** Docker Compose, GitHub Actions, Terraform

## Run locally

Requires Docker with Compose and Python 3.12+.

```bash
python scripts/setup.py
docker compose up --build
```

- App: **http://localhost:8000** (use `localhost`, not `127.0.0.1`; the origin check treats them as different sites)
- Dev email inbox for sign-up codes: **http://localhost:8025**

For real embeddings and answers, add AWS credentials and a Bedrock chat model ID enabled in your region to `.env`. Sign-in works without a model; documents show `failed` until the AI provider is configured.

Stop with `docker compose down` (avoid `down -v`, which deletes the database).

## Tests

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r backend/requirements.txt
PYTHONPATH=backend pytest backend/tests -q
```

The default run uses SQLite with mocked AI calls. Five PostgreSQL-only tests (row-level security, concurrent refresh replay, atomic rate limits) run when `TEST_DATABASE_URL` points to an isolated database named `nexus_test` with pgvector; CI does this automatically. Never point tests at a real database: they drop and recreate tables.

## Project structure

```
backend/app/     FastAPI app, RAG endpoints, indexing + mail workers, auth, migrations
backend/tests/   auth, isolation, concurrency and job-leasing tests
frontend/        HTML, CSS, JavaScript
infra/           Terraform for AWS
docs/            system design and trade-offs, AWS deployment design
```

## Current limits and roadmap

Being honest about what the retrieval does today:

- **Plain text / Markdown only**, up to 20,000 characters per document → next: PDF ingestion
- **Fixed-size character chunks** → next: sentence- and heading-aware chunking
- **Pure vector search, top-5** → next: hybrid BM25 + vector search with a cross-encoder reranker and a relevance threshold
- **No retrieval evaluation yet** → next: a labelled question set measuring recall@5, MRR and answer faithfulness, run in CI

## Author

**Nallapu Naveen** — MSc Applied Data Science, University of Essex · [GitHub](https://github.com/naveenvarma999) · [LinkedIn](https://www.linkedin.com/in/naveenvarma000/)
