# Elastic Beanstalk CI/CD Lab

A Python Flask application deployed to AWS Elastic Beanstalk, with infrastructure managed by CloudFormation Git Sync and application deployments automated via GitHub Actions.

## Architecture

- **Infrastructure** (`infra/template.yaml`) — S3 artifact bucket, RDS Postgres, the Elastic Beanstalk application/environment, and all supporting IAM roles. Provisioned and kept in sync with this repo via CloudFormation Git Sync (`deployment/deployment-file.json`).
- **Application** (`application.py`) — Flask app. `/` returns a status/version payload proving successful deployment; `/visits` reads and writes to RDS Postgres, proving live external-service connectivity.
- **CI/CD** (`.github/workflows/deploy.yml`) — on every push to `main`: packages the app into a zip, uploads it to S3, creates a new Elastic Beanstalk application version, and deploys it. No manual upload or console step required after initial setup.

## Deployment

- Elastic Beanstalk URL: `http://beanstalk-lab-env.eba-ev37uix3.us-east-1.elasticbeanstalk.com`
- The environment is created and managed entirely by Elastic Beanstalk — no manual EC2 provisioning or management.
- Database credentials are never stored in the CloudFormation template, in git, or as plaintext Elastic Beanstalk environment variables — the app fetches the RDS password from AWS SSM Parameter Store (SecureString) at runtime, using its own instance IAM role.

## Security design notes

### Why one step in the CI/CD pipeline mints its own ephemeral IAM key instead of using OIDC directly

The GitHub Actions workflow authenticates to AWS via OIDC (no long-lived keys) for every step — checkout, build, S3 upload, and Elastic Beanstalk application-version creation — except one: the final `aws elasticbeanstalk update-environment` call, which cannot run under any assumed-role session at all (OIDC or otherwise, see below). Rather than working around that with a permanent static credential stored in GitHub, the pipeline mints a short-lived IAM access key for a narrowly-scoped, single-purpose user (`beanstalk-lab-app-update-only`) at the start of the job, uses it once, and deletes it before the job ends. No AWS credential of any kind is stored in GitHub for this step.

**Why a session-based credential can't be used here:** Elastic Beanstalk computes a nested CloudFormation stack template each time an environment is updated. When that template exceeds CloudFormation's 51,200-byte inline size limit (it does, for this environment), Elastic Beanstalk stages it in an S3 location of its own choosing and hands CloudFormation a pre-signed URL to retrieve it. That hand-off does not correctly propagate STS session tokens, so the `UpdateEnvironment` call fails under *any* temporary/assumed-role session — whether obtained via GitHub OIDC or a plain `sts:AssumeRole` call.

**How this was confirmed, not assumed.** The identical IAM permission set was tested under three different credential types against the identical API call:

1. IAM role assumed via GitHub Actions OIDC → fails
2. The same role assumed directly via plain `sts:AssumeRole` (GitHub/OIDC not involved at all) → fails identically
3. The same permissions granted to a static IAM user with long-lived access keys (no session token) → succeeds

Because all three cases had identical permissions and only the credential *type* changed, this isolates the failure to session-token propagation specifically — ruling out an IAM scoping problem, which would have affected all three cases equally.

**How the exception is minimized — the just-in-time credential design:**

- The GitHub Actions OIDC role (`GitHubActionsDeployRole`, `infra/template.yaml`) is granted `iam:CreateAccessKey` / `iam:DeleteAccessKey` / `iam:ListAccessKeys`, scoped by `Resource` to the exact ARN of the `beanstalk-lab-app-update-only` user — nothing broader.
- At the start of each deploy job, the workflow deletes any stale keys left over from a crashed prior run (self-healing — IAM caps a user at 2 keys, so this prevents future runs from ever hitting that ceiling), creates a fresh key, uses it for exactly one `update-environment` call (with a short retry loop, since a freshly minted key can take a few seconds to propagate through IAM), and deletes it immediately after — in a step that runs even if the deploy step fails (`if: always()`).
- The credential's lifetime is the duration of one API call, not the lifetime of the pipeline. Every mint and delete is logged in CloudTrail, giving a full audit trail of exactly when a credential existed and which run created it.
- The `beanstalk-lab-app-update-only` user's own policy (`infra/persistent-identity.yaml`) still grants only what `UpdateEnvironment` and its downstream orchestration chain require — not `Resource: "*"` on `UpdateEnvironment` itself.
- The reasoning is documented here and inline in `infra/template.yaml` / `.github/workflows/deploy.yml`, making it a deliberate, auditable design rather than a silent shortcut.

This behavior looks like a genuine AWS platform limitation — session-token propagation through a pre-signed URL hand-off — rather than an account-specific misconfiguration, and would be a reasonable candidate for an AWS Support case in a production context. Until/unless AWS fixes it, ephemeral just-in-time credentials are the closest approximation to "fully OIDC" available: nothing static is ever stored, only a single-use key that exists for seconds.
