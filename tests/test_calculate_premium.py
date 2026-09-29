import pytest

# Expected premiums below were computed by hand from data/rate_table.json's
# age_bands / risk_multipliers, not copied from the handler's own output.

SUCCESS_CASES = [
    # (coverage_type, age, coverage_amount, risk_factors, expected_premium)
    ("life", 34, 500000, {"smoker": True}, 487.5),
    ("life", 34, 500000, {}, 325.0),
    ("life", 34, 500000, {"family_history": True}, 325.0),  # invalid key for life, silently filtered
    ("life", 34, 500000, {"smoker": True, "high_risk_occupation": False}, 487.5),  # False must not apply
    ("critical_illness", 50, 400000, {"smoker": True, "family_history": True}, 1164.8),
    ("funeral", 70, 50000, {"additional_dependents": True}, 218.5),
    ("life", 18, 500000, {}, 225.0),   # lower age-band boundary
    ("life", 75, 500000, {}, 1100.0),  # upper age-band boundary
    ("life", 34, 10_000_000, {}, 6500.0),  # coverage_amount upper boundary
    ("life", "34", 500000, {}, 325.0),  # numeric string age, must equal int 34 result
    # "age last birthday": fractional ages are floored, not rejected.
    ("life", 34.7, 500000, {}, 325.0),
    ("life", 34.99, 500000, {}, 325.0),
    ("life", "34.7", 500000, {}, 325.0),
    ("life", 30.9, 500000, {}, 225.0),  # floors to 30 -> still band 18-30 (rate 0.45)
]


@pytest.mark.parametrize(
    "coverage_type, age, coverage_amount, risk_factors, expected_premium", SUCCESS_CASES
)
def test_premium_success(
    calculate_premium, coverage_type, age, coverage_amount, risk_factors, expected_premium
):
    result = calculate_premium(
        {
            "age": age,
            "coverage_amount": coverage_amount,
            "coverage_type": coverage_type,
            "risk_factors": risk_factors,
        },
        None,
    )
    assert result["error"] is None
    assert result["premium_estimate"] == pytest.approx(expected_premium)
    assert isinstance(result["breakdown"], str) and result["breakdown"]


ERROR_CASES = [
    # (coverage_type, age, coverage_amount, risk_factors, expected_error_fields)
    ("disability", 62, 300000, {}, {"age"}),  # disability has no band above 60
    ("life", 17, 500000, {}, {"age"}),  # below lowest band
    ("life", 76, 500000, {}, {"age"}),  # above highest band
    ("motor", 40, 0, {}, {"coverage_type", "coverage_amount"}),  # age check skipped: coverage_type invalid
    ("life", 34, 10_000_001, {}, {"coverage_amount"}),
    ("life", 34, 0, {}, {"coverage_amount"}),
    ("life", 34, -100, {}, {"coverage_amount"}),
    ("life", "abc", 500000, {}, {"age"}),  # non-numeric string, no crash
    ("life", None, 500000, {}, {"age"}),  # missing age, no crash
    ("life", 17.9, 500000, {}, {"age"}),  # floors to 17 -> below lowest band (18)
    ("life", True, 500000, {}, {"age"}),  # bool has no "age last birthday"
    ("life", float("nan"), 500000, {}, {"age"}),
    ("life", float("inf"), 500000, {}, {"age"}),
    # Was a SUCCESS case ("truthy-but-not-True silently filtered") before
    # the Day 4 pre-work validation rules landed: a recognized risk_factor
    # key with a non-bool value is now bad input, not a silent no-op.
    ("life", 34, 500000, {"smoker": 1}, {"risk_factors"}),
]


@pytest.mark.parametrize(
    "coverage_type, age, coverage_amount, risk_factors, expected_error_fields", ERROR_CASES
)
def test_premium_error(
    calculate_premium, coverage_type, age, coverage_amount, risk_factors, expected_error_fields
):
    event = {
        "age": age,
        "coverage_amount": coverage_amount,
        "coverage_type": coverage_type,
        "risk_factors": risk_factors,
    }
    result = calculate_premium(event, None)

    assert set(result["error"].keys()) == expected_error_fields
    assert "premium_estimate" not in result
    assert "breakdown" not in result

    # error results must echo the inputs back. NaN != NaN, so that one
    # case needs its own comparison rather than ==.
    if isinstance(age, float) and age != age:
        assert isinstance(result["age"], float) and result["age"] != result["age"]
    else:
        assert result["age"] == age
    assert result["coverage_amount"] == coverage_amount
    assert result["coverage_type"] == coverage_type
    assert result["risk_factors"] == risk_factors


# --- Day 4 pre-work: stricter input validation (see PROGRESS.md) ---
# These reproduce real gaps in the current handler. They FAIL against the
# code as it stands before the fix in this same change; the fix in
# calculate_premium.py makes them pass without loosening any assertion
# here.


def test_age_is_floored_to_last_birthday(calculate_premium):
    # "Age last birthday" is the standard insurance convention: a
    # fractional age is floored, not rejected and not rounded. 34.7 and
    # 34.99 both mean "34 last birthday" — same premium as age 34.
    baseline = calculate_premium(
        {"age": 34, "coverage_amount": 500000, "coverage_type": "life", "risk_factors": {}},
        None,
    )
    for fractional_age in (34.7, 34.99, "34.7"):
        result = calculate_premium(
            {"age": fractional_age, "coverage_amount": 500000, "coverage_type": "life", "risk_factors": {}},
            None,
        )
        assert result["error"] is None
        assert result["premium_estimate"] == baseline["premium_estimate"]
        assert "age 34 (last birthday)" in result["breakdown"]


def test_coverage_amount_bool_is_rejected(calculate_premium):
    # bool is a subclass of int in Python, so isinstance(True, (int, float))
    # is True and 0 < True <= 10_000_000 passes (True behaves as 1) — a
    # boolean coverage_amount is silently accepted as 1 today.
    result = calculate_premium(
        {"age": 34, "coverage_amount": True, "coverage_type": "life", "risk_factors": {}},
        None,
    )
    assert "coverage_amount" in result["error"]
    assert "premium_estimate" not in result


def test_coverage_amount_more_than_two_decimals_is_rejected(calculate_premium):
    result = calculate_premium(
        {"age": 34, "coverage_amount": 1000.505, "coverage_type": "life", "risk_factors": {}},
        None,
    )
    assert "coverage_amount" in result["error"]
    assert "premium_estimate" not in result


def test_coverage_amount_two_decimals_succeeds(calculate_premium):
    result = calculate_premium(
        {"age": 34, "coverage_amount": 1000.50, "coverage_type": "life", "risk_factors": {}},
        None,
    )
    assert result["error"] is None


def test_risk_factors_non_bool_value_errors_on_risk_factors(calculate_premium):
    # {"smoker": "yes"} is truthy but not the real bool True; today it's
    # silently filtered out (treated the same as not supplying it at all)
    # instead of being flagged as bad input.
    result = calculate_premium(
        {"age": 34, "coverage_amount": 500000, "coverage_type": "life", "risk_factors": {"smoker": "yes"}},
        None,
    )
    assert "risk_factors" in result["error"]
    assert "premium_estimate" not in result


def test_risk_factors_as_list_errors_not_crash(calculate_premium):
    # Today: risk_factors.get(name) raises AttributeError on a list — an
    # unhandled crash, not a clean error dict.
    result = calculate_premium(
        {"age": 34, "coverage_amount": 500000, "coverage_type": "life", "risk_factors": ["smoker"]},
        None,
    )
    assert "risk_factors" in result["error"]
    assert "premium_estimate" not in result


def test_risk_factors_as_string_errors_not_crash(calculate_premium):
    # Same AttributeError crash today, for a string instead of a list.
    result = calculate_premium(
        {"age": 34, "coverage_amount": 500000, "coverage_type": "life", "risk_factors": "smoker"},
        None,
    )
    assert "risk_factors" in result["error"]
    assert "premium_estimate" not in result


# --- Follow-up to 44bfb06: message wording + characterization tests ---
# (see PROGRESS.md). The float("nan")/float("inf")/age-75.9/coverage_amount
# accept-and-reject lists below were already correct on the code as it
# stood before this change (verified by hand) — they're added here as
# characterization tests to protect that behavior across the Decimal-based
# currency-check refactor in this same change, not because they were
# failing. Only test_risk_factors_message_names_keys_in_plain_words is a
# genuine FAILING test against the code as it stands (current message is
# a Python list repr, e.g. "['smoker'] must be true or false").


def test_age_75_9_floors_to_75_still_valid(calculate_premium):
    # Upper age-band boundary (75) reached via flooring a fractional age,
    # not just an already-whole-number 75.
    result = calculate_premium(
        {"age": 75.9, "coverage_amount": 500000, "coverage_type": "life", "risk_factors": {}},
        None,
    )
    assert result["error"] is None
    assert result["premium_estimate"] == pytest.approx(1100.0)
    assert "age 75 (last birthday)" in result["breakdown"]


@pytest.mark.parametrize("coverage_amount", [1000.10, 0.29, 1234567.89, 1000.50, 500000])
def test_coverage_amount_valid_currency_values_accepted(calculate_premium, coverage_amount):
    result = calculate_premium(
        {"age": 34, "coverage_amount": coverage_amount, "coverage_type": "life", "risk_factors": {}},
        None,
    )
    assert result["error"] is None


@pytest.mark.parametrize(
    "coverage_amount",
    [1000.505, True, float("nan"), float("inf"), 0, -5, 10_000_000.01, 10_000_001],
)
def test_coverage_amount_invalid_currency_values_rejected(calculate_premium, coverage_amount):
    result = calculate_premium(
        {"age": 34, "coverage_amount": coverage_amount, "coverage_type": "life", "risk_factors": {}},
        None,
    )
    assert "coverage_amount" in result["error"]
    assert "premium_estimate" not in result


def test_risk_factors_message_names_keys_in_plain_words(calculate_premium):
    # Today: f"{bad_keys} must be true or false" renders as
    # "['smoker'] must be true or false" — a Python list repr, not
    # something you'd relay to a user or expect an agent to parse cleanly.
    result = calculate_premium(
        {"age": 34, "coverage_amount": 500000, "coverage_type": "life", "risk_factors": {"smoker": "yes"}},
        None,
    )
    assert result["error"]["risk_factors"] == "smoker must be true or false"
