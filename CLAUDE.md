# CLAUDE.md

Auto-loaded context for Claude Code. Keep this file short — it's loaded
into every message. Fuller detail lives in the files below; read them
before starting non-trivial work.

## Read first
- `CONTEXT.md` — overall purpose, standing decisions, scope boundaries.
  Don't re-litigate anything in there without a good reason.
- `PROGRESS.md` — current status, what's done, what's open. Update this
  at the end of any work session where something got completed or
  decided.
- `Project Brief` — full day-by-day plan and per-day Definition of Done.
- `data/Trap_data_reference.md` — deliberate edge cases in the synthetic
  data. Read before writing `check_claim_eligibility` or eval scenarios.

## Fixed facts — don't deviate without updating this file
- **Region: `eu-west-1` (Ireland)**, everything. Bedrock Knowledge Bases
  is not supported in af-south-1 (Cape Town) as of this project's start —
  don't suggest switching without re-checking that.
- S3 bucket: `sanlam-insurance-agent-devakmistry-2026`
- IAM role for Bedrock KB access: `sanlam-agent-bedrock-kb-role`
- Billing alarm lives in `us-east-1` (billing metrics are only queryable
  there, regardless of build region) — this is correct, not a mistake.
- **Bedrock Knowledge Base ID: `3VPWHXL63S`**, region eu-west-1, vector
  store is S3 Vectors (not OpenSearch). Any code calling
  `RetrieveAndGenerate` / `Retrieve` needs this KB ID.
- After any change to policy docs in S3, the KB data source must be
  manually re-synced — ingestion is not automatic on upload.
- AWS work happens under IAM user `devakmistry-admin`, not root.
- Known limitation: retrieval can return wrong-document chunks when a
  query combines a policy ID with a common term (see
  `data/Trap_data_reference.md`). Relevant to the Day 4 agent design —
  the `check_claim_eligibility` Lambda takes policy ID as a structured
  argument and is immune to this; only free-text KB queries are exposed.
  Consider whether tool schemas should carry policy ID as structured
  input rather than leaving it embedded in free-text KB queries.

## Working style
- Simple beats complex. If a task is fighting for more than roughly the
  time budgeted in the brief for that day, take the documented fallback
  and move on rather than pushing for the "better" solution.
- This is a portfolio/demo project on a hard deadline (submit Sunday),
  not production software. Don't add auth, rate limiting, retries,
  multi-tenancy, or other production hardening unless the brief asks
  for it — that's explicitly out of scope.
- Prefer AWS managed services over hand-built equivalents where the
  brief specifies it (e.g. Bedrock Knowledge Bases, not a hand-rolled
  RAG pipeline).

## Never do
- Never hardcode AWS credentials, access keys, or secrets in code or
  commit them to the repo. Use IAM roles / the configured CLI profile.
- Never create AWS resources in a region other than eu-west-1 (except
  the billing alarm, which is us-east-1 by necessity) without flagging
  it first.

## Build/test commands
*(empty — fill in once Lambdas and the agent loop exist, Day 3 onward)*
