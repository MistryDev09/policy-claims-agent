"""
Grading helpers for the Day 5 eval set (eval/run_eval.py). No AWS, no
network, no imports beyond the standard library, so these are unit
tested directly with plain Python data.
"""


def matches_call(actual_call, expected_entry):
    """
    actual_call: one trace entry, {"tool": str, "input": dict, "status": str}.
    expected_entry: {"tool": str, "arguments_contain": dict, "expect_status": optional str}.

    True only if:
    - actual_call["tool"] equals expected_entry["tool"] exactly.
    - every key in expected_entry["arguments_contain"] is present in
      actual_call["input"] with an equal value (a subset check; extra
      keys in actual_call["input"] are fine and are not inspected).
    - actual_call["status"] equals expected_entry["expect_status"],
      but only when expect_status is present in expected_entry; if it
      is absent, the status is not checked at all.
    """
    if actual_call["tool"] != expected_entry["tool"]:
        return False

    arguments_contain = expected_entry.get("arguments_contain", {})
    actual_input = actual_call.get("input", {})
    for key, value in arguments_contain.items():
        if key not in actual_input or actual_input[key] != value:
            return False

    if "expect_status" in expected_entry:
        if actual_call.get("status") != expected_entry["expect_status"]:
            return False

    return True


def check_tool_sequence(trace, expected_sequence):
    """
    Subsequence-in-order match: walks trace left to right, advancing a
    pointer into expected_sequence only when matches_call succeeds
    against the current expected entry; a trace entry that does not
    match the current expected entry is skipped over, not a failure by
    itself (extra, unrelated calls interspersed in the trace are fine).

    Returns (True, "") once every entry in expected_sequence has been
    matched in order somewhere in the trace. Otherwise returns
    (False, "<message identifying the first expected entry never
    matched, and its index>").

    An empty expected_sequence is treated as STRICT: it means the
    trace must ALSO be empty, i.e. "no tool of concern was called at
    all", not "nothing to check here, skip this". This is the
    behavior scenarios 6 and 10 in eval/scenarios.json rely on: an
    agent that calls any tool when it was expected to ask a question
    or refuse outright must fail this check, not pass it vacuously.
    """
    if not expected_sequence:
        if trace:
            return False, "expected_sequence is empty (strict) but the trace is not empty"
        return True, ""

    pointer = 0
    for call in trace:
        if pointer >= len(expected_sequence):
            break
        if matches_call(call, expected_sequence[pointer]):
            pointer += 1

    if pointer == len(expected_sequence):
        return True, ""

    return False, f"expected_sequence[{pointer}] ({expected_sequence[pointer]}) was never matched in the trace"


def normalize_for_match(text):
    """Lowercase, then strip every character that is not a digit."""
    return "".join(ch for ch in text.lower() if ch.isdigit())


def check_answer_contains_any(answer_text, candidates):
    """
    If candidates is empty, always returns True: there is nothing to
    check, so this is what lets a scenario with no fixed expected
    wording (eval/scenarios.json ids 3, 6, 10, 13) skip this check
    without being marked as failing it.

    Otherwise, normalizes both answer_text and every candidate with
    normalize_for_match (digits only, case-insensitive) and returns
    True if the normalized answer contains any normalized candidate as
    a substring. This matches amounts robustly against comma, space,
    or currency-symbol formatting differences, e.g. "R38,500" and
    "38500" normalize to the same digit string.
    """
    if not candidates:
        return True

    normalized_answer = normalize_for_match(answer_text)
    for candidate in candidates:
        normalized_candidate = normalize_for_match(candidate)
        if normalized_candidate and normalized_candidate in normalized_answer:
            return True
    return False
