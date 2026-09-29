import json
import os
from datetime import date, timedelta

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

with open(os.path.join(REPO_ROOT, "data", "claims.json")) as f:
    CLAIMS = json.load(f)

with open(os.path.join(REPO_ROOT, "data", "policies.json")) as f:
    POLICIES = {p["policy_id"]: p for p in json.load(f)}

# The handler's actual event shape (read from lambdas/check_eligibility/
# check_eligibility.py): policy_id, claim_type, claim_amount, claim_date
# are all REQUIRED (claim_date is NOT optional, despite the task prompt's
# assumption that it might be) — cli_demo.py defaults claim_date to
# today's date when the flag is omitted, but the handler itself has no
# default and errors without it. There is no "claim_category" field;
# the equivalent is "sub_limit_category" (a key into the policy's
# sub_limits dict). Both of these are real fields on the handler, so no
# xfail is needed for missing-field reasons anywhere in this file.


def _derive_extra_fields(claim, policy):
    """
    claims.json records outcomes as human-readable reason_codes, not as
    the handler's structured optional fields. To replay a claim against
    the real handler (which requires exclusion_code / sub_limit_category
    to be supplied explicitly — that's the point of making them
    structured instead of free text) we derive them here from the
    reason codes:
      - "EXCLUSION_MATCHED_<CODE>"       -> exclusion_code = "<CODE>"
      - "SUB_LIMIT_APPLIED_<CATEGORY>_<LIMIT>" -> sub_limit_category,
        matched against the policy's real sub_limits keys (the naive
        split on "_" doesn't work uniformly since categories like
        "child_under_21" contain underscores before the numeric suffix).
    This is a test-harness inference for replay purposes only — a real
    caller (the Day 4 agent) would supply these directly from its own
    claim intake, not by parsing a reason code string.
    """
    extra = {}
    for code in claim.get("reason_codes", []):
        if code.startswith("EXCLUSION_MATCHED_"):
            extra["exclusion_code"] = code[len("EXCLUSION_MATCHED_"):]
        elif code.startswith("SUB_LIMIT_APPLIED_"):
            body = code[len("SUB_LIMIT_APPLIED_"):]
            for category in policy.get("sub_limits", {}):
                if body.upper().startswith(category.upper()):
                    extra["sub_limit_category"] = category
                    break
    return extra


# claims.json has no diagnosis_date / claim_subtype fields (those are
# handler-only structured inputs the Day 4 agent would supply from its
# own claim intake, not something this flat dataset records). Now that
# the handler requires them in these two situations, the replay test
# needs real values to supply — taken from docs/trap-data-reference.md, not
# invented to make the test pass:
#   - CLM-012 is the documented diagnosis-date trap itself: "diagnosis
#     2024-03-15, policy start 2024-02-01, 90-day window ends ~2024-05-01"
#   - CLM-008/CLM-009 are the documented "collision claims against
#     third-party-only policies" trap
#   - CLM-002 has no distinct diagnosis date recorded anywhere; the most
#     defensible real value absent that data is date_filed itself (the
#     claim is denied either way — diagnosed the same day it was filed
#     is still well inside the 180-day waiting period)
REPLAY_EXTRA_FIELDS = {
    "CLM-002": {"diagnosis_date": "2025-12-15"},
    "CLM-008": {"claim_subtype": "collision"},
    "CLM-009": {"claim_subtype": "collision"},
    "CLM-012": {"diagnosis_date": "2024-03-15"},
}

# Approved claims whose reason code names a sub-limit — approved_amount
# must equal the sub-limit value quoted in that code, not the claimed
# amount.
APPROVED_SUBLIMIT_AMOUNTS = {
    "CLM-005": 350000,  # POL-0006 contents sub-limit
    "CLM-011": 20000,  # POL-0015 portable_electronics sub-limit
    "CLM-014": 20000,  # POL-0020 child_under_21 sub-limit
}

# CLM-007 is "pending" — this handler only ever returns eligible True/False,
# it doesn't model a pending outcome, so there's nothing meaningful to
# assert against. Explicitly skipped (not xfailed — there's no expected
# failure here, just an input the handler was never designed to classify)
# so it still shows up in the test report rather than silently vanishing.
REPLAY_PARAMS = [
    pytest.param(
        c,
        id=c["claim_id"],
        marks=pytest.mark.skip(reason="status is 'pending' — handler has no pending outcome to compare against")
        if c["status"] == "pending"
        else (),
    )
    for c in CLAIMS
]


@pytest.mark.parametrize("claim", REPLAY_PARAMS)
def test_replay_against_claims_json(check_eligibility, claim):
    policy = POLICIES[claim["policy_id"]]
    extra = _derive_extra_fields(claim, policy)
    extra.update(REPLAY_EXTRA_FIELDS.get(claim["claim_id"], {}))

    event = {
        "policy_id": claim["policy_id"],
        "claim_type": claim["claim_type"],
        "claim_amount": claim["amount"],
        "claim_date": claim["date_filed"],
        **extra,
    }
    result = check_eligibility(event, None)

    assert result["error"] is None, f"unexpected validation error for {claim['claim_id']}: {result.get('error')}"

    expected_eligible = claim["status"] == "approved"
    assert result["eligible"] is expected_eligible

    if expected_eligible:
        expected_amount = APPROVED_SUBLIMIT_AMOUNTS.get(claim["claim_id"], claim["amount"])
        excess = policy.get("excess")
        if excess:
            expected_amount = max(0, expected_amount - excess)
        assert result["approved_amount"] == expected_amount
    else:
        assert result["approved_amount"] == 0


def test_nonexistent_policy_errors_no_crash(check_eligibility):
    result = check_eligibility(
        {"policy_id": "POL-9999", "claim_type": "life", "claim_amount": 100000, "claim_date": "2024-01-01"},
        None,
    )
    assert result["error"] == {"policy_id": "not found"}
    assert "eligible" not in result
    # error results echo inputs back
    assert result["policy_id"] == "POL-9999"
    assert result["claim_amount"] == 100000


# --- claim_type mismatch as a self-correcting validation error, not a
# denial. The policy's real coverage type is metadata the caller cannot
# know in advance (it only ever gets a policy_id from the user), so a
# wrong guess should look like bad input the caller can retry, not a
# real denied claim with nothing to correct against.


def test_claim_type_mismatch_is_a_validation_error_naming_the_real_type(check_eligibility):
    # POL-0001 is a life policy; filing a motor claim against it.
    result = check_eligibility(
        {"policy_id": "POL-0001", "claim_type": "motor", "claim_amount": 10000, "claim_date": "2024-08-01"},
        None,
    )
    assert result["error"] == {
        "claim_type": "policy POL-0001 is a life policy, not motor; retry with claim_type 'life'"
    }
    assert "eligible" not in result
    assert "approved_amount" not in result
    assert "reason" not in result


def test_matching_claim_type_still_works(check_eligibility):
    # Regression: POL-0006 is a home policy; claim_type "home" is correct
    # and must proceed normally, no claim_type error.
    result = check_eligibility(
        {"policy_id": "POL-0006", "claim_type": "home", "claim_amount": 100000, "claim_date": "2026-01-20"},
        None,
    )
    assert result["error"] is None
    assert "claim_type" not in (result.get("error") or {})
    assert result["eligible"] is True


def test_unknown_policy_id_reports_only_policy_id_error_not_claim_type(check_eligibility):
    result = check_eligibility(
        {"policy_id": "POL-9999", "claim_type": "motor", "claim_amount": 10000, "claim_date": "2024-08-01"},
        None,
    )
    assert result["error"] == {"policy_id": "not found"}
    assert "claim_type" not in result["error"]


def test_claim_type_mismatch_combined_with_another_error_reports_both(check_eligibility):
    result = check_eligibility(
        {"policy_id": "POL-0001", "claim_type": "motor", "claim_amount": 10000, "claim_date": "not-a-date"},
        None,
    )
    assert set(result["error"].keys()) == {"claim_type", "claim_date"}


def test_claim_exceeds_overall_coverage_amount_is_capped(check_eligibility):
    # POL-0001 coverage_amount is 500,000; claim above it and past its
    # waiting period.
    policy = POLICIES["POL-0001"]
    result = check_eligibility(
        {
            "policy_id": "POL-0001",
            "claim_type": "life",
            "claim_amount": policy["coverage_amount"] + 100000,
            "claim_date": "2024-08-01",
        },
        None,
    )
    assert result["error"] is None
    assert result["eligible"] is True
    assert result["approved_amount"] == policy["coverage_amount"]
    assert f"CAPPED_AT_COVERAGE_AMOUNT_{policy['coverage_amount']}" in result["reason"]


def test_waiting_period_boundary(check_eligibility):
    # Computed from policies.json itself, not hardcoded — POL-0001's
    # start_date + waiting_period_days is the cutoff.
    policy = POLICIES["POL-0001"]
    start = date.fromisoformat(policy["start_date"])
    cutoff = start + timedelta(days=policy["waiting_period_days"])

    one_day_before = cutoff - timedelta(days=1)
    result_before = check_eligibility(
        {
            "policy_id": "POL-0001",
            "claim_type": "life",
            "claim_amount": 100000,
            "claim_date": one_day_before.isoformat(),
        },
        None,
    )
    assert result_before["error"] is None
    assert result_before["eligible"] is False
    assert result_before["reason"] == "WAITING_PERIOD_NOT_MET"

    result_on_cutoff = check_eligibility(
        {
            "policy_id": "POL-0001",
            "claim_type": "life",
            "claim_amount": 100000,
            "claim_date": cutoff.isoformat(),
        },
        None,
    )
    assert result_on_cutoff["error"] is None
    assert result_on_cutoff["eligible"] is True


# --- Day 4 pre-work: fail-closed on missing required-in-context fields
# (see PROGRESS.md). These reproduce real gaps in the current handler.
# They FAIL against the code as it stands before the fix in this same
# change; the fix in check_eligibility.py makes them pass without
# loosening any assertion here.


def test_critical_illness_without_diagnosis_date_errors(check_eligibility):
    # CLM-012's real inputs (POL-0018, critical_illness), but with NO
    # diagnosis_date supplied. Today this silently uses claim_date for
    # the waiting-period check and returns eligible=True — exactly the
    # failure mode the diagnosis-date trap exists to catch (a caller who
    # forgets to ask for the diagnosis date gets a wrong answer instead
    # of a prompt to go get one).
    result = check_eligibility(
        {
            "policy_id": "POL-0018",
            "claim_type": "critical_illness",
            "claim_amount": 1000000,
            "claim_date": "2024-06-01",
        },
        None,
    )
    assert "diagnosis_date" in result["error"]
    assert "eligible" not in result


def test_motor_third_party_fire_theft_without_claim_subtype_errors(check_eligibility):
    # POL-0010 is third_party_fire_theft; without claim_subtype the
    # handler can't tell a covered peril (fire/theft) from an excluded
    # one (collision), so today it silently approves everything.
    result = check_eligibility(
        {
            "policy_id": "POL-0010",
            "claim_type": "motor",
            "claim_amount": 60000,
            "claim_date": "2026-01-05",
        },
        None,
    )
    assert "claim_subtype" in result["error"]
    assert "eligible" not in result


def test_excess_deducted_from_approved_amount(check_eligibility):
    # POL-0005 (motor) carries a 6,500 excess, waiting_period_days=2.
    policy = POLICIES["POL-0005"]
    result = check_eligibility(
        {
            "policy_id": "POL-0005",
            "claim_type": "motor",
            "claim_amount": 45000,
            "claim_date": "2026-05-12",
        },
        None,
    )
    assert result["error"] is None
    assert result["eligible"] is True
    assert result["approved_amount"] == 45000 - policy["excess"]
    assert "excess" in result["reason"]


def test_excess_floors_at_zero_not_negative(check_eligibility):
    # POL-0012 (device) excess is 750; a claim smaller than the excess
    # must approve at 0, not a negative number, and the reason must say
    # plainly why nothing is payable — not just append "less R750 excess"
    # to a generic "within coverage limit" sentence that no longer holds
    # once the payout is zero. FAILS today: the reason text doesn't say
    # this explicitly.
    policy = POLICIES["POL-0012"]
    result = check_eligibility(
        {
            "policy_id": "POL-0012",
            "claim_type": "device",
            "claim_amount": 500,
            "claim_date": "2026-07-01",
        },
        None,
    )
    assert result["error"] is None
    assert result["eligible"] is True
    assert result["approved_amount"] == 0
    assert f"does not exceed the R{policy['excess']} excess" in result["reason"]


def test_excess_exactly_equal_to_claim_amount_floors_at_zero(check_eligibility):
    # claim_amount exactly equal to the excess — still nothing payable.
    policy = POLICIES["POL-0012"]
    result = check_eligibility(
        {
            "policy_id": "POL-0012",
            "claim_type": "device",
            "claim_amount": policy["excess"],
            "claim_date": "2026-07-01",
        },
        None,
    )
    assert result["error"] is None
    assert result["eligible"] is True
    assert result["approved_amount"] == 0
    assert f"does not exceed the R{policy['excess']} excess" in result["reason"]


def test_unknown_sub_limit_category_lists_valid_values(check_eligibility):
    result = check_eligibility(
        {
            "policy_id": "POL-0006",
            "claim_type": "home",
            "claim_amount": 100000,
            "claim_date": "2026-01-20",
            "sub_limit_category": "not_a_real_category",
        },
        None,
    )
    assert "eligible" not in result
    message = result["error"]["sub_limit_category"]
    for valid_category in POLICIES["POL-0006"]["sub_limits"]:
        assert valid_category in message


def test_unknown_exclusion_code_errors_and_lists_valid_values(check_eligibility):
    result = check_eligibility(
        {
            "policy_id": "POL-0001",
            "claim_type": "life",
            "claim_amount": 100000,
            "claim_date": "2024-08-01",
            "exclusion_code": "NOT_A_REAL_CODE",
        },
        None,
    )
    assert "eligible" not in result
    message = result["error"]["exclusion_code"]
    for valid_code in POLICIES["POL-0001"]["exclusion_codes"]:
        assert valid_code in message


# --- Follow-up to 44bfb06: preserve reason notes when excess wipes the
# payout. No real policy in policies.json combines excess with a
# sub_limit, or with deferred_period_days/a missing travel end_date, so
# these two cases are built against a synthetic policy inserted into
# POLICIES_BY_ID via monkeypatch (auto-reverted after each test). Both
# FAIL against the code as it stands: reason_notes is currently
# overwritten outright when excess wipes the payout, discarding whatever
# was already in it.


def test_excess_wipeout_preserves_sub_limit_note(check_eligibility_module, monkeypatch):
    fake_policy = {
        "policy_id": "POL-TEST-SUBLIMIT-EXCESS",
        "coverage_type": "home",
        "coverage_amount": 1_000_000,
        "sub_limits": {"contents": 400},
        "excess": 500,
        "start_date": "2020-01-01",
        "waiting_period_days": 0,
        "status": "active",
        "exclusion_codes": [],
    }
    monkeypatch.setitem(check_eligibility_module.POLICIES_BY_ID, fake_policy["policy_id"], fake_policy)

    result = check_eligibility_module.lambda_handler(
        {
            "policy_id": fake_policy["policy_id"],
            "claim_type": "home",
            "claim_amount": 2000,
            "claim_date": "2024-01-01",
            "sub_limit_category": "contents",
        },
        None,
    )
    assert result["error"] is None
    assert result["eligible"] is True
    assert result["approved_amount"] == 0  # sub-limit caps to 400, excess (500) then wipes it
    assert "SUB_LIMIT_APPLIED_CONTENTS_400" in result["reason"]
    assert "does not exceed the R500 excess" in result["reason"]


def test_excess_wipeout_preserves_deferred_period_caveat(check_eligibility_module, monkeypatch):
    fake_policy = {
        "policy_id": "POL-TEST-DEFERRED-EXCESS",
        "coverage_type": "disability",
        "coverage_amount": 100_000,
        "deferred_period_days": 7,
        "excess": 5000,
        "start_date": "2020-01-01",
        "waiting_period_days": 0,
        "status": "active",
        "exclusion_codes": [],
    }
    monkeypatch.setitem(check_eligibility_module.POLICIES_BY_ID, fake_policy["policy_id"], fake_policy)

    # No disability_onset_date supplied, so the deferred-period check is
    # skipped and annotated; claim_amount (3000) is below the excess
    # (5000), so it should wipe the payout while keeping that annotation.
    result = check_eligibility_module.lambda_handler(
        {
            "policy_id": fake_policy["policy_id"],
            "claim_type": "disability",
            "claim_amount": 3000,
            "claim_date": "2024-01-01",
        },
        None,
    )
    assert result["error"] is None
    assert result["eligible"] is True
    assert result["approved_amount"] == 0
    assert "deferred period not evaluated" in result["reason"]
    assert "does not exceed the R5000 excess" in result["reason"]


def test_error_echoes_inputs_and_keys_error_by_field(check_eligibility):
    event = {
        "policy_id": "POL-0001",
        "claim_type": "life",
        "claim_amount": -50,
        "claim_date": "not-a-date",
    }
    result = check_eligibility(event, None)

    assert set(result["error"].keys()) == {"claim_amount", "claim_date"}
    assert "eligible" not in result
    assert result["policy_id"] == "POL-0001"
    assert result["claim_type"] == "life"
    assert result["claim_amount"] == -50
    assert result["claim_date"] == "not-a-date"
