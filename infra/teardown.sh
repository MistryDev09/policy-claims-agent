#!/usr/bin/env bash
set -euo pipefail

REGION="eu-west-1"
FUNCTIONS=(sanlam-calculate-premium sanlam-check-eligibility)
ROLES=(sanlam-calculate-premium-role sanlam-check-eligibility-role)

echo "This will permanently delete both Lambda functions, both IAM roles,"
echo "and both log groups in $REGION."
read -r -p "Type 'yes' to continue: " CONFIRM
if [[ "$CONFIRM" != "yes" ]]; then
  echo "Aborted, nothing deleted."
  exit 1
fi

for fn in "${FUNCTIONS[@]}"; do
  echo "Deleting function $fn..."
  # Delete the function itself; "|| true" so an already-missing function
  # does not stop the rest of the teardown.
  aws lambda delete-function --function-name "$fn" --region "$REGION" || true

  log_group="/aws/lambda/$fn"
  echo "Deleting log group $log_group..."
  # Lambda creates this log group automatically on first invocation; it
  # is not removed by delete-function, so it needs its own delete call.
  aws logs delete-log-group --log-group-name "$log_group" --region "$REGION" || true
done

for role in "${ROLES[@]}"; do
  echo "Deleting inline policy and role $role..."
  # The inline policy must be removed before the role can be deleted,
  # IAM refuses to delete a role that still has attached policies.
  aws iam delete-role-policy --role-name "$role" --policy-name "${role}-logs" || true
  aws iam delete-role --role-name "$role" || true
done

echo "Teardown complete."
