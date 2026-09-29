"""
Compares the local handler against the deployed Lambda for a fixed set
of inputs. This file makes real AWS calls (boto3 lambda invoke) so it
is not run by Claude, only by the person operating this repo, after
infra/deploy_lambdas.sh has actually deployed both functions.
"""
import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
from cli_demo import _load_handler  # noqa: E402

REGION = "eu-west-1"
FUNCTION_NAMES = {
    "calculate_premium_estimate": "sanlam-calculate-premium",
    "check_claim_eligibility": "sanlam-check-eligibility",
}
LOCAL_HANDLERS = {
    "calculate_premium_estimate": ("calculate_premium", "calculate_premium.py"),
    "check_claim_eligibility": ("check_eligibility", "check_eligibility.py"),
}

# Fixed so results do not depend on the day this script is actually run.
CLAIM_DATE = "2026-09-28"

CASES = [
    ("calculate_premium_estimate", {"age": 35, "coverage_amount": 500000, "coverage_type": "life", "risk_factors": {"smoker": True}}),
    # Disability's 46-60 band starts at exactly 46, the band edge.
    ("calculate_premium_estimate", {"age": 46, "coverage_amount": 300000, "coverage_type": "disability", "risk_factors": {}}),
    ("calculate_premium_estimate", {"age": 40, "coverage_amount": 500000, "coverage_type": "pet", "risk_factors": {}}),
    # 34.7 floors to 34 (age last birthday).
    ("calculate_premium_estimate", {"age": 34.7, "coverage_amount": 500000, "coverage_type": "life", "risk_factors": {}}),
    ("check_claim_eligibility", {
        "policy_id": "POL-0005", "claim_type": "motor", "claim_amount": 45000,
        "claim_date": CLAIM_DATE, "claim_subtype": "collision",
    }),
    # POL-0006 is a home policy; claim_type "motor" exercises the
    # self-correcting mismatch error this session added.
    ("check_claim_eligibility", {
        "policy_id": "POL-0006", "claim_type": "motor", "claim_amount": 10000, "claim_date": CLAIM_DATE,
    }),
    ("check_claim_eligibility", {
        "policy_id": "POL-0018", "claim_type": "critical_illness", "claim_amount": 1000000,
        "claim_date": CLAIM_DATE, "diagnosis_date": "2024-03-15",
    }),
    ("check_claim_eligibility", {
        "policy_id": "POL-0020", "claim_type": "funeral", "claim_amount": 25000,
        "claim_date": CLAIM_DATE, "sub_limit_category": "child_under_21",
    }),
]


def call_local(tool_name, tool_input):
    subdir, filename = LOCAL_HANDLERS[tool_name]
    handler = _load_handler(subdir, filename)
    return handler(tool_input, None)


def call_lambda(client, tool_name, tool_input):
    response = client.invoke(
        FunctionName=FUNCTION_NAMES[tool_name],
        Payload=json.dumps(tool_input).encode("utf-8"),
    )
    payload = json.loads(response["Payload"].read())
    if "FunctionError" in response:
        return {"error": {"lambda": payload}}
    return payload


def main():
    import boto3

    client = boto3.client("lambda", region_name=REGION)

    passed = 0
    for i, (tool_name, tool_input) in enumerate(CASES, start=1):
        local_result = call_local(tool_name, tool_input)
        lambda_result = call_lambda(client, tool_name, tool_input)
        ok = local_result == lambda_result

        status = "PASS" if ok else "FAIL"
        print(f"[{i}] {tool_name} {tool_input} -> {status}")
        if ok:
            passed += 1
        else:
            print(f"    local:  {local_result}")
            print(f"    lambda: {lambda_result}")

    print(f"\n{passed}/{len(CASES)} passed")


if __name__ == "__main__":
    main()
