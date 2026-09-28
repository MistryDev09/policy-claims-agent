#!/usr/bin/env bash
set -euo pipefail

# Fixed deployment settings for this project (region locked to eu-west-1,
# see CLAUDE.md).
REGION="eu-west-1"
RUNTIME="python3.12"
ARCHITECTURE="x86_64"
TIMEOUT=10
MEMORY=128

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="$REPO_ROOT/build"
POLICIES_DIR="$REPO_ROOT/infra/policies"

# name|handler|zip path|role name, one entry per function to deploy.
FUNCTIONS=(
  "sanlam-calculate-premium|calculate_premium.lambda_handler|$BUILD_DIR/calculate_premium.zip|sanlam-calculate-premium-role"
  "sanlam-check-eligibility|check_eligibility.lambda_handler|$BUILD_DIR/check_eligibility.zip|sanlam-check-eligibility-role"
)

# Resolve the account ID at runtime only, this value is never hardcoded
# and never written to a file.
ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
# Also fetch the caller's own ARN, used below to refuse a root-user run.
CALLER_ARN="$(aws sts get-caller-identity --query Arn --output text)"

if [[ "$CALLER_ARN" == *":root" ]]; then
  echo "Refusing to deploy: caller is the account root user ($CALLER_ARN). Use the devakmistry-admin IAM user instead." >&2
  exit 1
fi

SUMMARY=()

deploy_one() {
  local function_name="$1" handler="$2" zip_path="$3" role_name="$4"
  local role_arn rendered_policy created_role function_arn

  echo "=== $function_name ==="
  created_role="false"

  # Look up the role first; only create it if it truly does not exist yet.
  if aws iam get-role --role-name "$role_name" >/dev/null 2>&1; then
    role_arn="$(aws iam get-role --role-name "$role_name" --query 'Role.Arn' --output text)"
  else
    # Create the role with the fixed Lambda trust policy (allows only
    # lambda.amazonaws.com to assume it).
    role_arn="$(aws iam create-role \
      --role-name "$role_name" \
      --assume-role-policy-document "file://$POLICIES_DIR/lambda-trust.json" \
      --query 'Role.Arn' --output text)"
    created_role="true"
  fi

  # Render the least-privilege logs policy template with the real
  # region, account ID, and function name, substituted via sed.
  rendered_policy="$(mktemp)"
  sed -e "s/__REGION__/$REGION/g" \
      -e "s/__ACCOUNT_ID__/$ACCOUNT_ID/g" \
      -e "s/__FUNCTION_NAME__/$function_name/g" \
      "$POLICIES_DIR/logs-policy.template.json" > "$rendered_policy"

  # Attach (or replace) the rendered logs policy as an inline policy on
  # the role.
  aws iam put-role-policy \
    --role-name "$role_name" \
    --policy-name "${role_name}-logs" \
    --policy-document "file://$rendered_policy"
  rm -f "$rendered_policy"

  # A newly created role is not immediately usable everywhere in AWS
  # (IAM is eventually consistent); create-function can fail with "the
  # role cannot be assumed" if used right away, so wait once here.
  if [[ "$created_role" == "true" ]]; then
    echo "Waiting 10s for IAM role propagation..."
    sleep 10
  fi

  # Tag the role for cost/ownership tracking.
  aws iam tag-role --role-name "$role_name" --tags Key=Project,Value=sanlam-insurance-agent

  if aws lambda get-function --function-name "$function_name" --region "$REGION" >/dev/null 2>&1; then
    # Function already exists: ship new code, then wait for the update
    # to finish applying before moving on to the next function.
    aws lambda update-function-code \
      --function-name "$function_name" \
      --zip-file "fileb://$zip_path" \
      --region "$REGION" >/dev/null
    aws lambda wait function-updated-v2 --function-name "$function_name" --region "$REGION"
  else
    # First deploy: create the function with the fixed runtime settings.
    aws lambda create-function \
      --function-name "$function_name" \
      --runtime "$RUNTIME" \
      --architectures "$ARCHITECTURE" \
      --role "$role_arn" \
      --handler "$handler" \
      --zip-file "fileb://$zip_path" \
      --timeout "$TIMEOUT" \
      --memory-size "$MEMORY" \
      --region "$REGION" >/dev/null
    aws lambda wait function-active-v2 --function-name "$function_name" --region "$REGION"
  fi

  # Read back the function's ARN for tagging and for the end-of-run summary.
  function_arn="$(aws lambda get-function --function-name "$function_name" --region "$REGION" --query 'Configuration.FunctionArn' --output text)"
  # Tag the function for cost/ownership tracking.
  aws lambda tag-resource --resource "$function_arn" --tags Project=sanlam-insurance-agent

  SUMMARY+=("$function_name -> $function_arn")
}

for entry in "${FUNCTIONS[@]}"; do
  IFS='|' read -r fn_name fn_handler fn_zip fn_role <<< "$entry"
  deploy_one "$fn_name" "$fn_handler" "$fn_zip" "$fn_role"
done

echo
echo "=== Deployed functions ==="
for line in "${SUMMARY[@]}"; do
  echo "$line"
done
