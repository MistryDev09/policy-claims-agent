# Sanlam Insurance Agent

## How to run
- Install dependencies: `pip install -r requirements.txt`
- Authenticate as an IAM user (not root) in `eu-west-1`: `aws login`

## Future work
- At real scale, the agent would call a `get_policy_details(policy_id)`
  lookup tool so valid sub-limit categories and exclusion codes come
  from a source of truth instead of a static enum baked into the tool
  schema.
