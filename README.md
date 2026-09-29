# Sanlam Insurance Agent

An AI agent that answers questions about insurance policies and performs
two real calculations (premium estimates and claim eligibility), built on
AWS and Amazon Bedrock. It exists as a portfolio piece for the Sanlam Data,
AI and Engineering Academy application: it shows hands-on AWS, Bedrock,
AgentCore and agentic engineering work on synthetic data, and is scoped as
a demo, not production software.

## Architecture

```
                         ┌─────────────────────┐
                         │   User (CLI chat)    │
                         └──────────┬───────────┘
                                    │ question
                                    ▼
                    ┌───────────────────────────────┐
                    │   Agent Loop (tool_loop.py)    │
                    │   Bedrock Converse API          │
                    │   Claude Sonnet 4.6              │
                    └───────┬───────────┬─────────────┘
                            │           │
              tool_use:     │           │  tool_use:
      calculate_premium_    │           │  check_claim_
        estimate /          │           │  eligibility
      check_claim_          │           │
        eligibility         │           │  search_policy_documents
                            ▼           ▼           │
              ┌─────────────────────────┐           │
              │   dispatch() backend     │           │
              │   switch (TOOL_BACKEND)  │           │
              └───┬───────┬───────┬─────┘           │
                  │        │        │                 │
              local    lambda    gateway               │
                  │        │        │                 │
                  ▼        ▼        ▼                 ▼
          ┌───────────────────────────────┐  ┌──────────────────────┐
          │  Two AWS Lambda functions:     │  │  Bedrock Knowledge    │
          │  - calculate_premium           │  │  Base (Retrieve API)  │
          │  - check_eligibility           │  │  S3 Vectors store     │
          │  (reached directly, or via     │  │  Synthetic policy     │
          │  AgentCore Gateway/MCP with    │  │  documents in S3      │
          │  Cognito JWT auth)             │  │                        │
          └───────────────────────────────┘  └──────────────────────┘
```

## AWS services used
- **Bedrock**: Converse API (Claude Sonnet 4.6), Knowledge Bases, S3 Vectors
- **Lambda**: `sanlam-calculate-premium`, `sanlam-check-eligibility`
- **AgentCore Gateway**: exposes both Lambdas as MCP tools
- **Cognito**: JWT auth for the Gateway
- **S3**: synthetic policy documents
- **IAM**: least-privilege roles for the Lambdas and the Knowledge Base
- **CloudWatch**: billing alarm (in `us-east-1`, by necessity)

## How to run
- `pip install -r requirements.txt`
- Log in as the IAM user (not root) in `eu-west-1`: `aws login`
- Set `TOOL_BACKEND` to `local` (default, no AWS), `lambda` or `gateway`
- For `gateway`, load the config first with `set -a; source .env; set +a`.
  Required variables (names only, in a gitignored `.env`): `GATEWAY_URL`,
  `TOKEN_URL`, `CLIENT_ID`, `CLIENT_SECRET`, `SCOPE`

## Eval results
24 scenarios (23 graded, 1 intentionally logged only). After an initial
run surfaced 3 scenario-design bugs that were then fixed, the graded
scenarios scored 23/23 on two gateway runs. See `docs/eval-findings.md` for the full account.

## Known limitations
- `sub_limit_category` and `exclusion_code` use a flat union enum across
  all policies, with server-side validation to self-correct wrong guesses
  (see `PROGRESS.md`).
- KB retrieval can return the wrong policy's chunks when a query combines
  a policy ID with a common term (see `docs/trap-data-reference.md`).
- There is no incident-date field, so `claim_date` doubles as the date
  used for waiting-period math (see `docs/eval-findings.md`).
- Per-claim-subtype waiting periods (theft vs. accidental damage) are not
  modelled (see `PROGRESS.md`).
- POL-0022 has no `end_date`, so its travel date-bounds check is skipped
  (see `PROGRESS.md`).
- `exclusion_code` is caller-asserted: the tool checks it is a real code
  on the policy, not whether it applies to the claim (see `PROGRESS.md`).
- No auth, rate limiting or multi-tenancy, by design for a demo (see
  `docs/context.md`).

## Future work
- A `get_policy_details` lookup tool, so valid sub-limits and exclusion
  codes come from a source of truth instead of a static enum.
- An `incident_date` field on `check_claim_eligibility`, separate from
  `claim_date`.
- AgentCore Runtime hosting (only the Gateway was completed).

## Further reading
- `docs/context.md`: purpose, standing decisions and scope boundaries.
- `docs/project-brief.md`: the day-by-day plan and definitions of done.
- `docs/trap-data-reference.md`: deliberate edge cases in the synthetic data.
- `docs/eval-findings.md`: full eval run history and the incident-date finding.
- `PROGRESS.md`: build log, what is done and what is open.
