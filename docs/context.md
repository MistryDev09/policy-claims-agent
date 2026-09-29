# Project Context

Quick primer. Read this first, then `project-brief.md` for the day-by-day
plan, then `PROGRESS.md` for what's actually been done. This file doesn't
change day to day — it's the "why" and "what," not the "what's left."

---

## What this is

An agent that answers questions about insurance policies and performs two
real calculations, deployed on AWS. Built to demonstrate AWS + Bedrock +
AgentCore + agentic engineering skills for a specific job application, not
to be a finished product.

**Why it exists:** applying to the Sanlam Data, AI and Engineering
Academy, closing 2 October 2026, targeting submission Thursday 1 October
(Friday 2 October as buffer). The
listing names AWS, Bedrock, AI AgentCore, Claude, and agentic engineering
explicitly. A hiring manager tip said to demonstrate AWS skills directly
— this project exists to prove that, nothing more.

**Working constraint:** 4-5 hours/day, Tue-Sun. Simple beats complex. If
a step fights for more than the time budgeted, take the documented
fallback and move on. A finished small thing beats an unfinished
impressive thing — this governs every scope decision in the project.

## The three things it actually does

1. **Knowledge base lookup** — answers questions from synthetic policy
   documents via Bedrock Knowledge Bases (managed RAG, not hand-built).
2. **`calculate_premium_estimate`** — a Lambda tool with real
   deterministic logic. No LLM arithmetic.
3. **`check_claim_eligibility`** — a Lambda tool with real rule-based
   logic against synthetic claims/policy data.

A Bedrock Converse API tool-use loop lets Claude decide which of these to
call for a given question. Deployed via AgentCore (Runtime + Gateway) if
that goes smoothly; documented fallback to plain Lambda + API Gateway if
it doesn't — either is a legitimate result, not a failure.

## Standing decisions already made (don't re-litigate these)

- **Region: `eu-west-1` (Ireland)**, for everything. Chosen over
  `af-south-1` (Cape Town) because Bedrock Knowledge Bases isn't on AWS's
  supported region list for af-south-1 yet, even though model invocation
  is. One region for the whole project, no mixing.
- **Managed RAG, not hand-built.** Default chunking, Titan embeddings,
  default vector store. Don't hand-tune retrieval — that's explicitly
  out of scope (see brief's "What we are deliberately not doing").
- **No Snowflake/dbt, no polished frontend, no production auth/rate
  limiting/multi-tenancy.** Out of scope by design, not oversight — say
  so plainly in the README rather than apologizing for it.
- **IAM roles are scoped deliberately**, not console-default. This is
  itself part of what's being demonstrated (the hiring manager tip was
  "show AWS skills directly") — least-privilege policies, not
  `AdministratorAccess`. (Exception: the human IAM user doing the build
  work — see the `devakmistry-admin` note below.)
- **Vector store: Amazon S3 Vectors**, not the OpenSearch Serverless
  "Quick create" default. OpenSearch Serverless has a minimum OCU
  allocation with real-world reports of ~$260/month even near-idle, which
  conflicts with the $15 CloudWatch billing alarm. S3 Vectors is storage +
  per-query billed with no idle compute floor, GA since Dec 2025,
  available in eu-west-1. Tradeoff: pure vector search, no keyword/hybrid
  layer (see `trap-data-reference.md`).
- **Self-managed "Knowledge Base with vector store" path**, not AWS's
  newer "Managed Knowledge Base" (launched June 2026, now the
  AWS-recommended default). Managed KB fully abstracts the embedding model
  and vector store choice. This project exists to demonstrate hands-on
  construction of the RAG pipeline (S3 → Titan embeddings → vector store)
  for a job application, so hiding those components defeats the purpose.
- **`claims.json` and `rate_table.json` are bundled into each Lambda's
  deployment package**, not stored in S3. They're static and small (14
  claims), read directly at runtime. S3 storage would only be justified if
  this data changed independently of code deploys or needed shared
  cross-service access.
- **Note: AWS root user cannot create Bedrock Knowledge Bases** (platform
  restriction). Created IAM user `devakmistry-admin` with
  `AdministratorAccess` for all project work going forward. Broader than
  least-privilege by design — a solo-account time tradeoff for a one-week
  portfolio project, not representative of production scoping.

## Where things stand

See `PROGRESS.md` for the current day-by-day status, what's done, and
what's still open. As of the last update: Day 1 complete (data + S3 +
IAM + billing alarm), Day 2 complete (Bedrock Knowledge Base
`sanlam-policy-kb`, S3 Vectors, retrieval testing).

## What "done" looks like for the whole week

- Working agent using ≥2 real tools plus a managed knowledge base
- Deployed on AWS (AgentCore or the documented fallback)
- Eval set with logged results
- Demo video, under 2 minutes
- README honest about scope and limitations
- Application submitted Thursday 1 October (Friday 2 October as buffer)

If a future session is unsure whether something is in scope, the test is:
does this prove AWS/Bedrock/agentic skill to a hiring manager reading it
in two minutes? If not, it's probably not worth today's hours.
