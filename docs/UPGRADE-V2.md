# Version 2 — security and reliability upgrade

This release improves the standalone AWS project. It does not modify or deploy the earlier Floot-hosted app.

## What changed and why

| Area | Previous behavior | Version 2 behavior |
|---|---|---|
| Distributed rate limiting | Fixed-window counters, permitting bursts at window boundaries | PostgreSQL token buckets with row locks, continuous refill, bounded burst and database time |
| Sessions | Absolute expiration only | 30-minute request inactivity timeout, five-session cap, session list, remote revocation and sign out everywhere |
| Password changes | Recovery flow only | Authenticated change requires the current password; failures share account lockout protection; all sessions revoked on success |
| Signing keys | One authentication secret | Separate production JWT key map, signed key ID, active-key selection and overlapping verification keys |
| Document isolation | Application ownership filters | Application filters plus forced PostgreSQL RLS and transaction-local user identity |
| Worker database access | One application database role | Separate indexer and mail roles with restricted table grants |
| Worker execution | External requests inside a long database transaction | Short claim/commit transactions, renewable leases, claim-token fencing and bounded retry/dead-letter states |
| Provider outage | Every request retries the unavailable provider | Shared circuit state, fail-fast rejection, cooldown and one recovery probe |
| Schema changes | Initial table creation | Explicit forward migration version 2, additive columns and one-time invalidation of version 1 sessions |
| Operations | Basic health checks | Request IDs, structured metadata logs, DB statement/lock deadlines, WAF configuration and storage alarm |
| Verification | Initial authentication suite | Additional session, key rotation, token-bucket boundary, worker takeover, circuit and migration tests; PostgreSQL policy tests in CI |

## Upgrade an existing installation

1. Back up the database and confirm that restoration works in staging. Retain the version 1 image digest and infrastructure state.
2. Stop/drain the old API, mail and indexing tasks. This upgrade requires a maintenance window; do not run version 1 and version 2 workers together during migration.
3. Create three additional Secrets Manager secrets: JWT signing-key map, indexer DB credentials, and mail DB credentials. See AWS.md for their formats and new Terraform variables.
4. Build and push the version 2 image. Set both Terraform service counts to zero, update the image and secret ARNs, and review/apply the infrastructure plan.
5. Run the migration task and check exit code zero. It adds missing columns, creates new tables, records schema version 2, installs RLS and grants separate runtime roles. The first migration revokes old sessions. Re-running the migration does not repeat that revocation.
6. Start two API replicas and one replica of each worker. Require users to sign in again. Verify every staging acceptance check in AWS.md and run the PostgreSQL tests in CI.
7. Connect alarms to incident notification, enable daily cleanup and record measured service limits before increasing traffic.

No destructive column removal occurs in this release. Nevertheless, do not redeploy the version 1 image blindly: its queries lack the required RLS identity and its worker schema/role expectations differ. Roll forward with a fix, or restore the pre-upgrade backup with the prior image under a reviewed rollback procedure. Restoring a backup loses changes made after that backup.

## JWT signing-key rotation

The production API reads `JWT_SIGNING_KEYS` as a JSON object such as `{"primary":"RANDOM_48_BYTE_SECRET","next":"ANOTHER_RANDOM_SECRET"}`. Use actual cryptographic secrets; these strings are shapes, not valid credentials. `JWT_ACTIVE_KID` names the signing key. Workers do not receive this signing-key secret.

For a routine rotation: add the new verification key to every API replica first, while keeping the current key active. Complete that rollout. Then change the active key and roll out again. Keep the previous key for at least the 15-minute access-token lifetime after the last old-key signer has stopped, plus an operational clock-skew margin. Remove the old key in a final rollout. Refresh sessions do not need the old signing key. Emergency compromise response may intentionally remove a key immediately and require reauthentication.

This rotation mechanism applies to JWT signing only. `AUTH_SECRET` still protects refresh digests, OTP digests and encrypted email payloads. Its rotation needs a maintenance procedure that invalidates sessions and handles pending encrypted email; it is not seamless.

## Explicit boundaries

This is an advanced application implementation, not a security certification. MFA/passkeys, organization RBAC, SAML/SCIM, managed secret rotation orchestration, malware scanning, streaming chat, cross-region disaster recovery and a full observability platform are not implemented. Do not advertise those features. PostgreSQL policies protect against missing application filters; they do not protect against a fully compromised API process that can select arbitrary transaction identity. Email is still at-least-once, and citations still need human/evaluation checks.
