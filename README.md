# Sanlam Insurance Agent

## Architecture

```
                              +----------------------------+
                              |   Bedrock Knowledge Base    |
                              |   (Retrieve, direct boto3)  |
                              +--------------+---------------+
                                             ^
                                             |
   user  --text-->  agent loop (Converse API, Claude Sonnet 4.6)
                                             |
                          +------------------+------------------+
                          |                                     |
              calculate_premium_estimate           check_claim_eligibility
                          |                                     |
                          +------------------+------------------+
                                             |
                         TOOL_BACKEND = local / lambda / gateway
                                             |
              +---------------+   +---------+---------+
              | local: plain  |   | lambda: boto3      |
              | Python call   |   | invoke() on the    |
              | (default)     |   | deployed function   |
              +---------------+   +---------------------+
                                             |
                              +--------------+---------------+
                              | gateway: AgentCore Gateway    |
                              | (MCP, JSON-RPC tools/call)     |
                              | JWT auth via Cognito           |
                              | client credentials             |
                              +---------------------------------+
```

The Knowledge Base tool is always a direct `bedrock-agent-runtime`
`retrieve()` call, in every `TOOL_BACKEND`. Only the two Lambda-backed
tools switch between running as a plain Python function, a real
`lambda.invoke()`, or a call through the AgentCore Gateway.

## AWS services used
- **Bedrock**: Converse API (Claude Sonnet 4.6, tool use), Knowledge
  Bases (managed RAG over the synthetic policy documents), S3 Vectors
  (the Knowledge Base's vector store).
- **Lambda**: `sanlam-calculate-premium`, `sanlam-check-eligibility`.
- **IAM**: least-privilege roles for both Lambdas (logs only, scoped to
  each function's own ARN) and for the Knowledge Base.
- **S3**: the bucket holding the synthetic policy documents.
- **CloudWatch**: a billing alarm (in `us-east-1`, by necessity; billing
  metrics are account-wide and only queryable there).
- **AgentCore Gateway**: fronts the two Lambdas as MCP tools behind one
  gateway URL.
- **Cognito**: inbound JWT auth for the Gateway, issuing OAuth2
  client-credentials tokens.

## How to run
- Install dependencies: `pip install -r requirements.txt`
- Authenticate as an IAM user (not root) in `eu-west-1`: `aws login`
- The agent loop's `TOOL_BACKEND` env var picks how the two Lambda-backed
  tools run: `local` (default, plain Python functions, no AWS), `lambda`
  (real deployed Lambda via boto3), or `gateway` (an AgentCore Gateway
  over MCP, authenticated via a Cognito client-credentials token).
- For the gateway backend, load its config into the shell first:
  `set -a; source .env; set +a`. The required variable names are
  `GATEWAY_URL`, `TOKEN_URL`, `CLIENT_ID`, `CLIENT_SECRET`, `SCOPE`, each
  set in `.env` (gitignored, never committed).

## Eval results

`eval/scenarios.json` holds 24 scenarios: 18 agent-level (run through
the full Converse/Gateway loop) and 6 Lambda-level (direct), covering
document Q&A, premium calculation, claim eligibility, multi-tool
questions, self-correction, and refusals. One scenario is intentionally
excluded from pass/fail (a known data-modeling limitation, logged not
graded).

Two full runs against the deployed AgentCore Gateway both scored 23/23
on the strict scenarios, after an initial run surfaced three
scenario-design bugs that were then fixed. See `PROGRESS.md`'s "Day 5
eval results" for the full account, including a run that scored 22/23
on an unrelated, still-open scenario flakiness. Raw detail lives in
`eval/scenarios.json` and `eval/results/`.

A small eval set run a handful of times is evidence of behavior on
these specific cases, not a guarantee of correctness in general,
especially given the incident-date finding below.

## Known limitations
- Uses synthetic policy and claims data only, not real policyholder
  data.
- No auth, rate limiting, or multi-tenancy on the agent loop itself.
  This is deliberate: a portfolio/demo project on a fixed deadline, not
  production software.
- Per-claim-subtype waiting periods (for example theft vs. accidental
  damage having opposite wait structures) are not modelled; a single
  flat `waiting_period_days` is used regardless of subtype.
- POL-0022's missing `end_date` is not modelled; its travel date-bounds
  check is skipped, the same as the genuinely dateless
  `annual_multi_trip` policies.
- `exclusion_code` is caller-asserted: the handler only checks whether
  the code the caller supplied is a real code on that policy, it does
  not decide whether an exclusion applies to a claim's facts. The agent
  (or a human) decides that before calling the tool.
- `sub_limit_category` and `exclusion_code` use a flat union enum
  across all policies, rather than a schema scoped to each individual
  policy. Real values are still validated server-side, so a wrong guess
  self-corrects via the tool's error message rather than being silently
  accepted.
- Knowledge Base retrieval trap: including a policy ID in a free-text
  query can return chunks from the wrong policy (see
  `Trap_data_reference.md`). A system prompt rule mitigates this by
  retrying the search once the real coverage type is known, but this is
  a prompt rule, not a guarantee.
- The AgentCore Gateway strips JSON Schema `enum` keys from tool
  schemas, so `agent/gateway_schema.json` lists each field's valid
  values in words in the description instead of as an `enum`.
- The agent's KB retry behaviour after a missed search is a
  system-prompt instruction, not a deterministic guarantee. Two manual
  gateway runs both succeeded, but a query that includes a policy ID
  (against the tool's own guidance) has been observed even when it
  happened to land on the right document, so a wrong-document pull
  under this pattern remains possible and is covered by a dedicated
  Day 5 eval scenario.
- `check_claim_eligibility` has no distinct incident-date field;
  `claim_date` is used both for waiting-period math and as the nominal
  filing date. When a user describes a past incident date separately
  from today, whether the agent maps it onto `claim_date` is not
  guaranteed and was observed to vary between runs during Day 5
  evaluation. When it is not mapped correctly, the agent has been
  observed to catch and correct the resulting tool answer by
  cross-referencing the retrieved policy document, but this is not a
  guaranteed safeguard.

## Future work
- At real scale, the agent would call a `get_policy_details(policy_id)`
  lookup tool so valid sub-limit categories and exclusion codes come
  from a source of truth instead of a static enum baked into the tool
  schema.
- Knowledge Base retrieval can still miss the right document when a
  query uses a common term shared across many policies (for example
  "theft" pulling in motor and device policies instead of the intended
  home policy). A system prompt rule that retries the search once the
  real coverage type is known helps in practice, but it is a prompt
  rule, not a guarantee. The deterministic fix is a metadata filter on
  the retrieve call, scoping the search to the specific policy's
  document by ID instead of relying on semantic ranking alone.
- AgentCore Runtime hosting was not attempted; only the Gateway was
  completed for Day 4.
- An `incident_date` field on `check_claim_eligibility`, separate from
  `claim_date` (the filing date), so waiting-period and deferred-period
  math is always evaluated against the date the loss actually occurred
  rather than depending on how the agent maps a user's stated date
  onto the existing field. Found via the Day 5 eval set (scenario 13);
  not implemented yet, since it needs both a schema change and a full
  retest cycle.
