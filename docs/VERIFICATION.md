# Version 2 verification record

Date: 8 October 2026.

## Completed in this workspace

**24 automated tests passed; five PostgreSQL-specific tests were skipped.** The executed suite used a temporary SQLite database and FastAPI's HTTP test client.

Covered behavior:

- Signup, one-use/expired OTPs, Argon2id hashes, five-failure password lockout, OTP lockout surviving resends, password recovery and session invalidation.
- JWT issuer/audience/signature validation paths, rotation/replay rejection, logout blacklisting, CSRF/origin checks and request-size rejection.
- Idle sessions rejected for both access and refresh; session cap; remote session revocation; logout everywhere; current-password verification on password changes.
- JWT verification-key overlap and removal, continuous token-bucket refill and refusal to reset the budget at a fixed-window boundary.
- Per-user document/history filtering and atomic indexing with mocked embeddings.
- Index retry exhaustion and stale-worker fencing after lease takeover; shared circuit open/probe/recovery behavior.
- Version 1 column migration and once-only migration effects.
- Request correlation/security headers, expired email suppression, and mock SMTP acceptance with payload erasure.
- Google callback using an actual locally generated RSA signature with mocked token exchange, PKCE configuration and single-use state.

JavaScript syntax and Python compilation checks passed. Terraform and example variables parsed with an HCL parser. The source has not been certified secure by an external audit.

## Supplied but not executed here

The five PostgreSQL-specific tests cover concurrent password failures, simultaneous refresh replay, atomic rate budgets, forced RLS under a non-superuser role with pooled-connection identity reset, and index-worker denial of account-table access. The CI workflow runs them against an isolated PostgreSQL/pgvector service. SQLite results cannot establish PostgreSQL lock or RLS correctness.

The previous attempt to run PostgreSQL here was blocked because the environment could not switch to a database service user. Docker/Terraform runtimes were unavailable. Therefore no Docker build, Compose startup, Terraform provider validation/plan, or AWS apply is claimed. CI contains Terraform validation and dependency auditing; neither workflow has been executed on the user's repository.

The prior Chromium download failed. No browser visual or end-to-end success is claimed for the new Account security screen. Syntax and backend route tests are available; run real-browser checks in staging.

No real SES customer delivery, Google consent flow, Bedrock inference, WAF enforcement test, production load test, failover exercise or penetration test was performed. Account credentials and a staging deployment are required. The provided read-only load script measures only basic API admission/latency, not RAG capacity.

See AWS.md for staging acceptance checks and UPGRADE-V2.md for migration/key-rotation procedures.
