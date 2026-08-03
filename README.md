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

### Why one step in the CI/CD pipeline uses a static IAM credential instead of OIDC

The GitHub Actions workflow authenticates to AWS via OIDC (no long-lived keys) for every step — checkout, build, S3 upload, and Elastic Beanstalk application-version creation — except one: the final `aws elasticbeanstalk update-environment` call. That one step uses a narrowly-scoped, single-purpose IAM user (`beanstalk-lab-app-update-only`) instead of the OIDC role used everywhere else.

**Why this is necessary:** Elastic Beanstalk computes a nested CloudFormation stack template each time an environment is updated. When that template exceeds CloudFormation's 51,200-byte inline size limit (it does, for this environment), Elastic Beanstalk stages it in an S3 location of its own choosing and hands CloudFormation a pre-signed URL to retrieve it. That hand-off does not correctly propagate STS session tokens, so the `UpdateEnvironment` call fails under *any* temporary/assumed-role session — whether obtained via GitHub OIDC or a plain `sts:AssumeRole` call.

**How this was confirmed, not assumed.** The identical IAM permission set was tested under three different credential types against the identical API call:

1. IAM role assumed via GitHub Actions OIDC → fails
2. The same role assumed directly via plain `sts:AssumeRole` (GitHub/OIDC not involved at all) → fails identically
3. The same permissions granted to a static IAM user with long-lived access keys (no session token) → succeeds

Because all three cases had identical permissions and only the credential *type* changed, this isolates the failure to session-token propagation specifically — ruling out an IAM scoping problem, which would have affected all three cases equally.

**How the exception is minimized:**

- The static user's policy grants `elasticbeanstalk:UpdateEnvironment` scoped to exactly one environment ARN, not `Resource: "*"`.
- It is the only static credential anywhere in the pipeline — not a blanket fallback used elsewhere.
- The reasoning is documented here and inline in `infra/template.yaml` / `.github/workflows/deploy.yml`, making it a deliberate, auditable exception rather than a silent shortcut.

This behavior looks like a genuine AWS platform limitation — session-token propagation through a pre-signed URL hand-off — rather than an account-specific misconfiguration, and would be a reasonable candidate for an AWS Support case in a production context.
