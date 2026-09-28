import importlib.util
import os

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_check_helpers():
    # eval/ is not a package either, same importlib.util pattern used
    # for agent/tool_loop.py in test_tool_loop.py.
    path = os.path.join(REPO_ROOT, "eval", "check_helpers.py")
    spec = importlib.util.spec_from_file_location("check_helpers", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def check_helpers():
    return _load_check_helpers()


# --- matches_call ---


def test_matches_call_exact_match(check_helpers):
    actual = {"tool": "check_claim_eligibility", "input": {"policy_id": "POL-0006"}, "status": "success"}
    expected = {"tool": "check_claim_eligibility", "arguments_contain": {"policy_id": "POL-0006"}, "expect_status": "success"}
    assert check_helpers.matches_call(actual, expected) is True


def test_matches_call_subset_with_extra_actual_keys(check_helpers):
    actual = {
        "tool": "check_claim_eligibility",
        "input": {"policy_id": "POL-0006", "claim_type": "home", "claim_amount": 10000},
        "status": "success",
    }
    expected = {"tool": "check_claim_eligibility", "arguments_contain": {"policy_id": "POL-0006"}}
    assert check_helpers.matches_call(actual, expected) is True


def test_matches_call_status_mismatch_fails(check_helpers):
    actual = {"tool": "check_claim_eligibility", "input": {"policy_id": "POL-0006"}, "status": "error"}
    expected = {"tool": "check_claim_eligibility", "arguments_contain": {"policy_id": "POL-0006"}, "expect_status": "success"}
    assert check_helpers.matches_call(actual, expected) is False


def test_matches_call_tool_name_mismatch_fails(check_helpers):
    actual = {"tool": "calculate_premium_estimate", "input": {}, "status": "success"}
    expected = {"tool": "check_claim_eligibility", "arguments_contain": {}}
    assert check_helpers.matches_call(actual, expected) is False


def test_matches_call_missing_argument_key_fails(check_helpers):
    actual = {"tool": "check_claim_eligibility", "input": {"claim_type": "home"}, "status": "success"}
    expected = {"tool": "check_claim_eligibility", "arguments_contain": {"policy_id": "POL-0006"}}
    assert check_helpers.matches_call(actual, expected) is False


def test_matches_call_no_expect_status_means_status_not_checked(check_helpers):
    actual = {"tool": "check_claim_eligibility", "input": {"policy_id": "POL-0006"}, "status": "error"}
    expected = {"tool": "check_claim_eligibility", "arguments_contain": {"policy_id": "POL-0006"}}
    assert check_helpers.matches_call(actual, expected) is True


# --- check_tool_sequence ---


def test_check_tool_sequence_in_order_full_match(check_helpers):
    trace = [
        {"tool": "check_claim_eligibility", "input": {"policy_id": "POL-0006", "claim_type": "motor"}, "status": "error"},
        {"tool": "check_claim_eligibility", "input": {"policy_id": "POL-0006", "claim_type": "home"}, "status": "success"},
    ]
    expected_sequence = [
        {"tool": "check_claim_eligibility", "arguments_contain": {"claim_type": "motor"}, "expect_status": "error"},
        {"tool": "check_claim_eligibility", "arguments_contain": {"claim_type": "home"}, "expect_status": "success"},
    ]
    ok, reason = check_helpers.check_tool_sequence(trace, expected_sequence)
    assert ok is True
    assert reason == ""


def test_check_tool_sequence_out_of_order_fails(check_helpers):
    trace = [
        {"tool": "check_claim_eligibility", "input": {"claim_type": "home"}, "status": "success"},
        {"tool": "check_claim_eligibility", "input": {"claim_type": "motor"}, "status": "error"},
    ]
    expected_sequence = [
        {"tool": "check_claim_eligibility", "arguments_contain": {"claim_type": "motor"}, "expect_status": "error"},
        {"tool": "check_claim_eligibility", "arguments_contain": {"claim_type": "home"}, "expect_status": "success"},
    ]
    ok, reason = check_helpers.check_tool_sequence(trace, expected_sequence)
    assert ok is False
    assert reason != ""


def test_check_tool_sequence_extra_unrelated_calls_interspersed_still_passes(check_helpers):
    trace = [
        {"tool": "search_policy_documents", "input": {"query": "home insurance"}, "status": "success"},
        {"tool": "check_claim_eligibility", "input": {"claim_type": "motor"}, "status": "error"},
        {"tool": "search_policy_documents", "input": {"query": "theft waiting period"}, "status": "success"},
        {"tool": "check_claim_eligibility", "input": {"claim_type": "home"}, "status": "success"},
    ]
    expected_sequence = [
        {"tool": "check_claim_eligibility", "arguments_contain": {"claim_type": "motor"}, "expect_status": "error"},
        {"tool": "check_claim_eligibility", "arguments_contain": {"claim_type": "home"}, "expect_status": "success"},
    ]
    ok, reason = check_helpers.check_tool_sequence(trace, expected_sequence)
    assert ok is True
    assert reason == ""


def test_check_tool_sequence_strict_empty_against_nonempty_trace_fails(check_helpers):
    trace = [{"tool": "calculate_premium_estimate", "input": {}, "status": "success"}]
    ok, reason = check_helpers.check_tool_sequence(trace, [])
    assert ok is False
    assert reason != ""


def test_check_tool_sequence_strict_empty_against_empty_trace_passes(check_helpers):
    ok, reason = check_helpers.check_tool_sequence([], [])
    assert ok is True
    assert reason == ""


def test_check_tool_sequence_reports_which_expected_entry_was_never_matched(check_helpers):
    trace = [{"tool": "check_claim_eligibility", "input": {"claim_type": "motor"}, "status": "error"}]
    expected_sequence = [
        {"tool": "check_claim_eligibility", "arguments_contain": {"claim_type": "motor"}, "expect_status": "error"},
        {"tool": "search_policy_documents", "arguments_contain": {}, "expect_status": "success"},
    ]
    ok, reason = check_helpers.check_tool_sequence(trace, expected_sequence)
    assert ok is False
    assert "1" in reason  # index of the never-matched entry
    assert "search_policy_documents" in reason


# --- normalize_for_match ---


def test_normalize_for_match_lowercases_and_strips_non_digits(check_helpers):
    assert check_helpers.normalize_for_match("R38,500") == "38500"
    assert check_helpers.normalize_for_match("Approved: R487.50/month") == "48750"
    assert check_helpers.normalize_for_match("HIV") == ""
    assert check_helpers.normalize_for_match("180") == "180"


# --- check_answer_contains_any ---


def test_check_answer_contains_any_empty_candidates_always_passes(check_helpers):
    assert check_helpers.check_answer_contains_any("anything at all", []) is True
    assert check_helpers.check_answer_contains_any("", []) is True


def test_check_answer_contains_any_currency_normalization_matches(check_helpers):
    assert check_helpers.check_answer_contains_any("Your approved amount is R38,500.", ["38500"]) is True


def test_check_answer_contains_any_no_match_fails(check_helpers):
    assert check_helpers.check_answer_contains_any("Your approved amount is R38,500.", ["99999"]) is False


def test_check_answer_contains_any_any_one_of_several_candidates_matches(check_helpers):
    assert check_helpers.check_answer_contains_any("The premium is R487.50 per month.", ["999", "487.50"]) is True
