import json
import math
import os
from decimal import Decimal

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
        age: number or numeric string, floored to a whole number — "age
            last birthday", the standard insurance convention: 34.7 and
            "34.7" both become 34, 30.9 becomes 30. Rejected outright
            (not just floored to 0 or silently coerced) for a bool, None,
            a non-numeric string, NaN, or +/-inf — none of those have a
            meaningful "age last birthday". The floored value is what
            gets band-checked and is echoed in the breakdown string.
        coverage_amount: number, > 0 and <= 10,000,000, finite (NaN and
            +/-inf rejected), at most 2 decimal places (it's a currency
            amount — checked via Decimal(str(x)), not round(x, 2) == x,
            since that's the more robust way to detect "more than 2
            decimal places present" for a float), not a bool.
        coverage_type: one of VALID_COVERAGE_TYPES
        risk_factors: dict[str, bool], optional, defaults to {}. Must be
            a dict, else rejected on "risk_factors" (not a crash). Keys
            that aren't valid multipliers for the given coverage_type are
            silently filtered out — but a key that IS valid for this
            coverage_type must have a real bool value (not "yes", 1, etc)
            or the whole risk_factors input is rejected, naming the bad
            key(s) in plain words (e.g. "smoker must be true or false").
            Note: this check only runs when coverage_type is itself
            valid — if coverage_type is invalid there's no rate table to
            check keys against, so a non-bool value on a would-be-valid
            key isn't reported in that case (the coverage_type error
            takes priority).

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

    # independent of coverage_type, can always be checked. Checked as an
    # explicit chain (not one big `or`) so the isfinite check always runs
    # before any rounding/Decimal work, rather than relying on the
    # accident that NaN/inf already fail the 0 < x <= 10_000_000
    # comparison via Python's NaN-comparisons-are-False semantics.
    coverage_amount_error = "must be a positive number, max 10,000,000, with at most 2 decimal places"
    if isinstance(coverage_amount, bool) or not isinstance(coverage_amount, (int, float)):
        # bool is a subclass of int in Python, so isinstance(True, (int,
        # float)) would otherwise be True and True == 1 would silently
        # pass as a coverage_amount of 1.
        errors["coverage_amount"] = coverage_amount_error
    elif not math.isfinite(coverage_amount):
        errors["coverage_amount"] = coverage_amount_error
    elif not (0 < coverage_amount <= 10_000_000):
        errors["coverage_amount"] = coverage_amount_error
    elif Decimal(str(coverage_amount)).as_tuple().exponent < -2:
        # Decimal(str(x)) instead of round(x, 2) == x: checks the decimal
        # places actually present in the value rather than relying on
        # binary-float round-trip equality, which is the more robust way
        # to answer "does this currency amount have more than 2 decimal
        # places" for a float.
        errors["coverage_amount"] = coverage_amount_error

    # age band check only runs if coverage_type was valid — this is the
    # "skip if coverage_type invalid" rule you decided on
    age = None
    matched_band = None
    if "coverage_type" not in errors:
        if isinstance(age_raw, bool):
            # bool is an int subclass; True/False have no "age last
            # birthday".
            errors["age"] = "must be a number (age last birthday)"
        elif isinstance(age_raw, (int, float)):
            # math.isfinite is False for both NaN and +/-inf, in one call
            # — an int is always finite, so this only ever rejects a bad
            # float.
            if not math.isfinite(age_raw):
                errors["age"] = "must be a number (age last birthday)"
            else:
                # "Age last birthday": floor, don't round or reject —
                # 34.7 and 34.99 are both still 34.
                age = math.floor(age_raw)
        elif isinstance(age_raw, str):
            try:
                parsed = float(age_raw)
            except ValueError:
                errors["age"] = "must be a number (age last birthday)"
            else:
                if not math.isfinite(parsed):
                    errors["age"] = "must be a number (age last birthday)"
                else:
                    age = math.floor(parsed)
        else:
            errors["age"] = "must be a number (age last birthday)"

        if "age" not in errors:
            bands = RATE_TABLE[coverage_type]["age_bands"]
            matched_band = next(
                (b for b in bands if b["min_age"] <= age <= b["max_age"]),
                None
            )
            if matched_band is None:
                errors["age"] = f"no rate band for age {age} under {coverage_type}"

    # risk_factors must be a dict — a list or string has no valid multiplier
    # keys to check and would otherwise crash the lookups below with an
    # AttributeError instead of returning a clean error.
    if not isinstance(risk_factors, dict):
        errors["risk_factors"] = "must be a dict of risk factor name to true/false"
    elif "coverage_type" not in errors:
        # Keys that ARE valid multipliers for this coverage_type must have
        # a real bool value (not "yes", 1, etc) — unknown keys are still
        # silently filtered, per the existing rule, but a recognized key
        # with a non-bool value is treated as bad input, not filtered.
        # Gated on "coverage_type not in errors" — if coverage_type itself
        # is invalid, there's no rate table to check keys against, so a
        # non-bool value on a would-be-valid key isn't reported here (the
        # coverage_type error takes priority; risk_factors is left alone).
        valid_multipliers = RATE_TABLE[coverage_type]["risk_multipliers"]
        bad_keys = [
            name for name in valid_multipliers
            if name in risk_factors and not isinstance(risk_factors[name], bool)
        ]
        if bad_keys:
            # Plain words, not a Python list repr: "smoker must be true or
            # false", not "['smoker'] must be true or false".
            errors["risk_factors"] = f"{', '.join(bad_keys)} must be true or false"

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

    breakdown_parts = [f"age {age} (last birthday)", f"base rate R{base_premium:.2f}"]
    for name, mult in applied.items():
        breakdown_parts.append(f"x {name} multiplier {mult}")
    breakdown = " ".join(breakdown_parts)

    return {
        "premium_estimate": premium_estimate,
        "breakdown": breakdown,
        "error": None,
    }