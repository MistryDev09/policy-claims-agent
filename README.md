# Sanlam Insurance Agent

## How to run
- Install dependencies: `pip install -r requirements.txt`
- Authenticate as an IAM user (not root) in `eu-west-1`: `aws login`

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
