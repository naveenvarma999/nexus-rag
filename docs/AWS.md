# Deploy version 2 to your AWS account

This configuration creates chargeable AWS resources. It has not been applied in this environment. Review `terraform plan`, IAM permissions, region availability and account limits before applying it. Use a staging environment first. There is no cloud deployment hidden in the local startup command.

For an existing version 1 installation, follow [UPGRADE-V2.md](UPGRADE-V2.md) first. The instructions below provision the current version.

## 1. Prepare the account

You need:

- An existing VPC with DNS support, at least two private subnets in different availability zones, and outbound connectivity. API tasks need access to Google and AWS endpoints; ECR image pulls, CloudWatch, SES, Secrets Manager and Bedrock must be reachable. Use your organization’s VPC/NAT or suitable VPC endpoints plus internet egress for Google.
- A Route 53 hosted zone and a validated ACM certificate in the deployment region for your app domain, such as `nexus.example.com`.
- A private ECR repository for the container image. Enable image scanning and an image retention policy.
- AWS CLI v2, Docker and Terraform >=1.6. Configure an AWS identity authorized for the resources in `infra/main.tf`.
- Bedrock access to Titan Text Embeddings V2 and a Converse-compatible chat model or inference profile in your region. Some models require provider access/use-case setup. Fill the exact model/profile identifiers and permitted resource ARNs; cross-region inference profiles also require destination model permissions.

The Terraform module provisions RDS, not the VPC, ECR repository, DNS zone, certificate, model access or provider credentials. The private subnets must already exist.

## 2. Configure customer email

In SES in the deployment region:

1. Verify the sender domain, publish the requested DKIM records and configure a suitable DMARC policy.
2. Request SES production access if your account is in the sandbox. Sandbox accounts cannot send arbitrary customer email without verifying recipients.
3. Choose a sender address at that verified domain; put it in `ses_from_email` and supply the corresponding identity ARN.
4. Configure SES event publishing for deliveries, bounces and complaints, and route failed-message alerts to operations. The application stores SES acceptance/message ID; it does not yet ingest these delivery events.

The worker uses its IAM task role. Never put AWS account keys in frontend code. Signup reports a generic pending-email response, not a false guarantee that delivery succeeded. Monitor `email_outbox` pending/failed states and CloudWatch worker errors. Do not log email body or codes.

## 3. Configure Google

Create a Google Cloud OAuth client of type Web application. Configure the consent screen, allowed audience/test users and publishing requirements for your product. Add this exact authorized redirect URI:

```
https://nexus.example.com/api/auth/google/callback
```

For local testing also add `http://localhost:8000/api/auth/google/callback`. Put the client ID in configuration and client secret in Secrets Manager. Only `openid email profile` scopes are requested. Google sign-in and email/password signup are separate account creation paths. Existing password accounts are not automatically linked to matching Google emails.

## 4. Create secrets

Create these Secrets Manager secrets using the AWS console or your organization’s approved secret tooling:

| Secret | Contents |
|---|---|
| Authentication | Plain string containing at least 48 cryptographically random bytes encoded as URL-safe text |
| JWT signing keys | JSON map of key IDs to random signing keys, e.g. `{"primary":"YOUR_48_BYTE_RANDOM_SECRET"}` |
| Google client | Plain Google OAuth client-secret string |
| Indexer database | JSON `username` beginning with `nexus_indexer` and a random 32+ character `password` |
| Mail database | JSON `username` beginning with `nexus_mail` and a random 32+ character `password` |
| Application database | JSON object with `username` beginning with `nexus_app` and a `password` of at least 32 random characters |

For example, the database secret format is `{"username":"nexus_app","password":"YOUR_RANDOM_PASSWORD"}`. Use real random values, never this example. Supply secret ARNs in Terraform, not secret contents. RDS creates and manages its separate administrator secret automatically. The migration task creates/updates the limited database role. API tasks use the application role; indexer and mail tasks use their own restricted database roles. JWT signing keys and the Google client secret are injected only into API tasks. Set `jwt_signing_keys_secret_arn`, `jwt_active_kid`, `database_index_secret_arn` and `database_mail_secret_arn` alongside the original variables. The ECS execution role reads startup secrets; container task roles do not receive general Secrets Manager access.

If secrets use customer-managed KMS keys, add the required key-specific `kms:Decrypt` permission to the execution role and key policy before deploying. The provided configuration assumes the default service-managed encryption keys.

RDS admin-secret rotation is managed by RDS. Changing the application database password requires rerunning the migration task and restarting the services in a coordinated maintenance window. Restart ECS tasks after changing injected secrets; running containers do not automatically refresh their environment. Authentication-secret rotation invalidates sessions and needs outbox handling described in DESIGN.md.

## 5. Build and push

Create your ECR repository if it does not exist, then authenticate Docker using AWS CLI. Replace account, region and repository below. Choose `linux/amd64` because the task definition uses the default x86_64 Fargate runtime.

```bash
aws ecr get-login-password --region eu-west-2 | docker login --username AWS --password-stdin ACCOUNT.dkr.ecr.eu-west-2.amazonaws.com
docker build --platform linux/amd64 -t ACCOUNT.dkr.ecr.eu-west-2.amazonaws.com/nexus:release-1 .
docker push ACCOUNT.dkr.ecr.eu-west-2.amazonaws.com/nexus:release-1
```

Resolve the pushed image digest in ECR and use the immutable `repository@sha256:...` URI in `image_uri`. The Docker build fetches AWS's official RDS CA bundle. Rebuild periodically to refresh operating-system packages and the CA bundle; review dependency updates with CI. The application runs as UID 10001 with a read-only root filesystem in ECS.

## 6. Provision without starting services

```bash
cd infra
cp terraform.tfvars.example terraform.tfvars
# Edit every REPLACE/ACCOUNT value. Keep api_count=0 and worker_count=0.
terraform init
terraform fmt
terraform validate
terraform plan -out=deployment.plan
terraform apply deployment.plan
```

Use an encrypted remote Terraform state backend with locking under your organization’s controls. Backend configuration is deliberately account-specific and not hard-coded here. State contains infrastructure identifiers and secret ARNs; protect it. Do not commit `terraform.tfvars`, plans or state files.

RDS is Multi-AZ with encrypted storage, automatic minor upgrades, 14-day backups and deletion protection. The ALB is private and also protected against accidental deletion. API Gateway is reachable only at the custom domain because the default execute-api hostname is disabled. DNS propagation can take time.

## 7. Run the schema migration

Use the Terraform outputs to run the migration task in the private subnets. Save a `network.json` locally containing your actual subnets and task security group:

```json
{"awsvpcConfiguration":{"subnets":["subnet-A","subnet-B"],"securityGroups":["sg-FROM-TERRAFORM-OUTPUT"],"assignPublicIp":"DISABLED"}}
```

Then:

```bash
aws ecs run-task --region eu-west-2 --cluster NEXUS_CLUSTER \
  --launch-type FARGATE --platform-version 1.4.0 \
  --task-definition MIGRATION_TASK_DEFINITION_ARN \
  --network-configuration file://network.json
```

Use the returned task ARN with `aws ecs wait tasks-stopped`, then `aws ecs describe-tasks`. **Check the container exit code is zero** and inspect the `migration` CloudWatch log stream. Waiting for “stopped” alone is not proof of success. Migration enables pgvector, creates tables and the HNSW index, applies the recorded version 2 column upgrade, installs row-level policies and grants the API, indexing and mail roles their separate permissions. If enabling the extension fails, verify your chosen RDS PostgreSQL version supports pgvector and that the task uses the RDS administrator secret.

The migration command handles initial installation and the explicit version 2 upgrade. Future releases need their own recorded migrations. No development test database should be placed in the production database instance.

## 8. Start the application

Set `api_count = 2` and `worker_count = 1` in your values, then review/apply another Terraform plan. One separate worker service handles mail and one handles indexing. The API scales between two and six tasks based on CPU. Set larger worker counts only after measuring provider quotas and DB capacity. Terraform may reset API desired count on later applies; review plans during autoscaling activity.

Open the app at your HTTPS domain. Run these real staging checks before customer launch:

- Signup to an email you control, receive the SES email, verify it and sign in.
- Five wrong password attempts trigger a full hour lockout; verify recovery remains available.
- Reset password using a real email code; previously signed-in browsers lose access.
- Complete Google authorization and verify that an existing local account is not silently linked.
- Sign out, then confirm a previously copied access token is rejected.
- Upload text/Markdown, observe pending → ready, ask a question and open cited excerpts.
- Create a second account and verify it cannot list, delete or retrieve the first account’s documents/history.
- Run the PostgreSQL concurrency test suite against an isolated `nexus_test` database, not production.
- Exercise 429 responses under a controlled load test; measure latency, DB connections, Bedrock spend and queue age.
- Test DB failover, an API deployment, email-worker restart, secret rotation and backup restoration.

## 9. Operate it

Attach the included unhealthy-target alarm to your incident topic. Add dashboards/alerts for gateway 5xx/latency/throttles, ECS CPU/memory/task count, RDS connections/storage/latency, SES bounces/complaints and worker queue age/failures. Raw request/response payload logging is intentionally absent to avoid password, OTP, OAuth code and document leaks.

Schedule the regular API task with a command override of `["python","-m","app.cleanup"]` once per day using EventBridge Scheduler or your existing scheduler. It needs the same private network configuration and application DB role; do not schedule the administrator migration task for cleanup. EventBridge scheduling and alert routing are account-specific setup steps, not provisioned in this module.

Application health paths: `/health` checks the process; `/ready` checks DB connectivity. ALB uses `/ready`. Provider health is checked by actual operations, not by an expensive recurring inference call. If the database is unavailable the application fails closed for authentication.

No deployment or load test can establish “perfect” rate limiting or availability. Review measured SLOs and incident procedures for the traffic you actually serve.


## Version 2 staging checks

- Let a session exceed the 30-minute request inactivity limit; verify both access and refresh are rejected. Turn off background polling during this test.
- Open six separately signed-in browsers; verify that the oldest session is revoked at the five-session cap. Revoke another browser from Account security.
- Change a password using the current-password check; confirm all old sessions are invalidated.
- Rotate JWT keys using the overlap procedure in UPGRADE-V2.md and verify old valid access tokens remain usable until intentional retirement.
- Run the non-superuser RLS tests and worker-permission test in the isolated PostgreSQL CI database.
- Stop an indexing worker after it claims a document, wait for lease expiry and restart workers. Confirm takeover and one final set of chunks. Force five provider failures to exercise retry exhaustion.
- Simulate an AWS provider outage and observe the circuit open, reject extra calls, admit one probe and close after recovery.
- Check WAF metrics on authentication paths and source-IP throttles. WAF sampling is off; do not enable payload/credential capture without redaction and a clear access policy.
- Run `TARGET_URL=https://YOUR-STAGING-DOMAIN python scripts/load_test.py` for a small read-only admission/latency probe. This does not measure RAG inference throughput or certify a production SLO.
- Inspect `X-Request-ID` and metadata logs; ensure no cookies, OTPs, passwords or document text are logged.

The GitHub security workflow audits Python dependencies and validates Terraform with the AWS provider. These checks are supplied, not claimed to have passed against your account. Review action versions and pin action commits according to your organization’s supply-chain policy before connecting a production deployment workflow.
