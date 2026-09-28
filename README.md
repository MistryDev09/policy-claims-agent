# Sanlam Insurance Agent

## How to run
- Install dependencies: `pip install -r requirements.txt`
- Authenticate as an IAM user (not root) in `eu-west-1`: `aws login`
- The agent loop's `TOOL_BACKEND` env var picks how the two Lambda-backed
  tools run: `local` (default, plain Python functions, no AWS), `lambda`
  (real deployed Lambda via boto3), or `gateway` (an AgentCore Gateway
  over MCP, authenticated via a Cognito client-credentials token). The
  gateway backend needs its config in `.env` (never committed) and
  loaded into the shell before running anything:
  `set -a; source .env; set +a`. The variable names it reads are
  `GATEWAY_URL`, `CLIENT_ID`, `CLIENT_SECRET`, `TOKEN_URL`, `SCOPE`, each
  set in `.env` (gitignored, never committed).

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
