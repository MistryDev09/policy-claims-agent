import json
import os

# Loaded once, outside the handler, at module import time — not inside
# lambda_handler. Lambda reuses the same execution environment across
# "warm" invocations, so file reads / setup done at module level only
# happen once per container, not once per call. Doing this inside the
# handler would work, just slower on every invocation.
#
# Resolved relative to this file's own location, not the process cwd —
# Lambda's working directory at invocation is /var/task, not necessarily
# wherever this file sits once packaged into a deployment zip.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(BASE_DIR, "rate_table.json")) as f:
    RATE_TABLE = json.load(f)

VALID_COVERAGE_TYPES = ["life", "critical_illness", "disability", "funeral"]


def lambda_handler(event, context):
    """
    Input event:
        age: number, cast to int (rejected if not a whole number, e.g.
            "34.7" is invalid input, not silently truncated)
        coverage_amount: number, > 0 and <= 10,000,000
        coverage_type: one of VALID_COVERAGE_TYPES
        risk_factors: dict[str, bool], optional, defaults to {}. Keys
            that aren't valid multipliers for the given coverage_type
            are silently filtered out, not treated as an error.

    Success return:
        {"premium_estimate": number, "breakdown": str, "error": None}

    Error return (any validation failure):
        {"age": ..., "coverage_amount": ..., "coverage_type": ...,
         "risk_factors": ..., "error": {"<field>": "<description>", ...}}
        premium_estimate/breakdown are absent entirely, not present-and-null.

    Validation order: coverage_type validity and coverage_amount bounds
    are checked independently of each other; the age-band check only runs
    if coverage_type was valid (there's no rate table to validate age
    against otherwise). All applicable errors are collected, not
    short-circuited on the first one.
    """
    age_raw = event.get("age")
    coverage_amount = event.get("coverage_amount")
    coverage_type = event.get("coverage_type")
    risk_factors = event.get("risk_factors", {})

    errors = {}

    # coverage_type checked first — everything else that touches
    # RATE_TABLE[coverage_type] depends on this being valid.
    if coverage_type not in VALID_COVERAGE_TYPES:
        errors["coverage_type"] = f"must be one of {VALID_COVERAGE_TYPES}"

    # independent of coverage_type, can always be checked
    if not isinstance(coverage_amount, (int, float)) or not (0 < coverage_amount <= 10_000_000):
        errors["coverage_amount"] = "must be a positive number, max 10,000,000"

    # age band check only runs if coverage_type was valid — this is the
    # "skip if coverage_type invalid" rule you decided on
    age = None
    matched_band = None
    if "coverage_type" not in errors:
        try:
            # int("34.7") raises ValueError — fractional-age strings are
            # rejected, not truncated via int(float(age_raw)). Age is a
            # whole number of years; silently truncating would hide a
            # data-quality problem from the caller.
            age = int(age_raw)
        except (TypeError, ValueError):
            errors["age"] = "must be a whole number"
        else:
            bands = RATE_TABLE[coverage_type]["age_bands"]
            matched_band = next(
                (b for b in bands if b["min_age"] <= age <= b["max_age"]),
                None
            )
            if matched_band is None:
                errors["age"] = f"no rate band for age {age} under {coverage_type}"

    if errors:
        return {
            "age": age_raw,
            "coverage_amount": coverage_amount,
            "coverage_type": coverage_type,
            "risk_factors": risk_factors,
            "error": errors,
        }

    # --- past this point every input is known-valid ---

    base_rate_per_1000 = matched_band["base_rate_per_1000"]
    base_premium = (coverage_amount / 1000) * base_rate_per_1000

    # silently filter risk_factors to only keys valid for this
    # coverage_type — this is the "filtered out, not errored" rule
    valid_multipliers = RATE_TABLE[coverage_type]["risk_multipliers"]
    applied = {
        name: mult for name, mult in valid_multipliers.items()
        if risk_factors.get(name) is True
    }

    combined_multiplier = 1.0
    for mult in applied.values():
        combined_multiplier *= mult

    premium_estimate = round(base_premium * combined_multiplier, 2)

    breakdown_parts = [f"base rate R{base_premium:.2f}"]
    for name, mult in applied.items():
        breakdown_parts.append(f"x {name} multiplier {mult}")
    breakdown = " ".join(breakdown_parts)

    return {
        "premium_estimate": premium_estimate,
        "breakdown": breakdown,
        "error": None,
    }