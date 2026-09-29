"""
Runs the Day 5 eval set (eval/scenarios.json) end to end. This file
makes real AWS calls (boto3 bedrock-runtime / bedrock-agent-runtime,
and if TOOL_BACKEND=gateway, real HTTP calls to the AgentCore Gateway
and Cognito), so it is not run by Claude, only by the person operating
this repo.
"""
import json
import os
import sys
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(BASE_DIR)
AGENT_DIR = os.path.join(REPO_ROOT, "agent")

sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, AGENT_DIR)
sys.path.insert(0, BASE_DIR)

from cli_demo import _load_handler  # noqa: E402
import tool_loop  # noqa: E402
from check_helpers import matches_call, check_tool_sequence, check_answer_contains_any  # noqa: E402

SCENARIOS_PATH = os.path.join(BASE_DIR, "scenarios.json")
RESULTS_DIR = os.path.join(BASE_DIR, "results")

# Maps a lambda-level scenario's "tool" field to the (subdir, filename)
# cli_demo._load_handler needs. Kept as a small dict, the same reuse
# pattern tool_loop.py and verify_lambdas.py already use for this.
LAMBDA_TOOL_LOADERS = {
    "calculate_premium.lambda_handler": ("calculate_premium", "calculate_premium.py"),
    "check_eligibility.lambda_handler": ("check_eligibility", "check_eligibility.py"),
}


def _expected_matches(actual, expected):
    """
    Subset-compares a lambda handler's result dict against a
    scenario's "expected" dict, reusing matches_call's exact subset
    logic for ordinary keys. A key ending in "_contains" is a named
    exception: the corresponding field (the key with that suffix
    stripped) is checked with a case-insensitive substring match
    instead of exact equality, e.g. "reason_contains" checks
    actual["reason"] for a substring, never exact equality. Returns
    (bool, list of mismatch descriptions).
    """
    plain_expected = {}
    contains_expected = {}
    for key, value in expected.items():
        if key.endswith("_contains"):
            contains_expected[key[: -len("_contains")]] = value
        else:
            plain_expected[key] = value

    mismatches = []

    ok = matches_call(
        {"tool": "_", "input": actual, "status": "_"},
        {"tool": "_", "arguments_contain": plain_expected},
    )
    if not ok:
        for key, value in plain_expected.items():
            if actual.get(key) != value:
                mismatches.append(f"{key}: expected {value!r}, got {actual.get(key)!r}")

    for field, substring in contains_expected.items():
        actual_value = str(actual.get(field, ""))
        if substring.lower() not in actual_value.lower():
            mismatches.append(f"{field}: expected to contain {substring!r}, got {actual_value!r}")

    return (len(mismatches) == 0), mismatches


def run_lambda_scenario(scenario):
    subdir, filename = LAMBDA_TOOL_LOADERS[scenario["tool"]]
    handler = _load_handler(subdir, filename)
    result = handler(scenario["input"], None)
    ok, mismatches = _expected_matches(result, scenario["expected"])
    return ok, result, mismatches


def _read_expected_answer_contains_any(scenario):
    """
    expected_answer_contains_any is either a bare list (mode="digits",
    the original shape, kept for backward compatibility) or an object
    {"mode": "text"|"digits", "values": [...]}. Returns (candidates,
    mode) either way, so run_agent_scenario always calls
    check_answer_contains_any the same way regardless of which shape a
    given scenario uses.
    """
    field = scenario["expected_answer_contains_any"]
    if isinstance(field, list):
        return field, "digits"
    return field["values"], field["mode"]


def run_agent_scenario(scenario, client, kb_client):
    messages = [{"role": "user", "content": [{"text": scenario["question"]}]}]
    final_text, trace = tool_loop.run_turn(messages, client=client, kb_client=kb_client)

    if "follow_up" in scenario:
        messages.append({"role": "user", "content": [{"text": scenario["follow_up"]}]})
        final_text, trace = tool_loop.run_turn(messages, client=client, kb_client=kb_client)

    sequence_ok, sequence_reason = check_tool_sequence(trace, scenario["expected_tool_sequence"])
    candidates, mode = _read_expected_answer_contains_any(scenario)
    answer_ok = check_answer_contains_any(final_text, candidates, mode=mode)

    ok = sequence_ok and answer_ok
    reason = ""
    if not sequence_ok:
        reason = sequence_reason
    elif not answer_ok:
        reason = "final answer did not contain any expected phrase"

    return ok, final_text, trace, reason


def main():
    with open(SCENARIOS_PATH) as f:
        scenarios = json.load(f)

    import boto3

    client = boto3.client("bedrock-runtime", region_name=tool_loop.REGION)
    kb_client = boto3.client("bedrock-agent-runtime", region_name=tool_loop.REGION)

    os.makedirs(RESULTS_DIR, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_path = os.path.join(RESULTS_DIR, f"run_{timestamp}.md")
    report_lines = [f"# Eval run {timestamp}\n\n", f"Backend: {tool_loop.TOOL_BACKEND}\n\n"]

    by_category = {}
    passed = 0
    logged = 0
    total = len(scenarios)

    for scenario in scenarios:
        category = scenario["category"]
        by_category.setdefault(category, {"count": 0, "pass": 0, "fail": 0, "logged": 0})
        by_category[category]["count"] += 1

        if scenario["level"] == "lambda":
            ok, actual, reason = run_lambda_scenario(scenario)
            report_lines.append(f"## Scenario {scenario['id']} ({category}, lambda)\n\n")
            report_lines.append(f"Input: {scenario['input']}\n\n")
            report_lines.append(f"Result: {actual}\n\n")
        else:
            ok, final_text, trace, reason = run_agent_scenario(scenario, client, kb_client)
            report_lines.append(f"## Scenario {scenario['id']} ({category}, agent)\n\n")
            report_lines.append(f"Question: {scenario['question']}\n\n")
            if "follow_up" in scenario:
                report_lines.append(f"Follow-up: {scenario['follow_up']}\n\n")
            for t in trace:
                report_lines.append(f"- tool={t['tool']} input={t['input']} status={t['status']} result={t['result']}\n")
            report_lines.append(f"\n**Answer:** {final_text}\n\n")

        if scenario.get("strict", True) is False:
            verdict = "LOGGED"
            logged += 1
            by_category[category]["logged"] += 1
        elif ok:
            verdict = "PASS"
            passed += 1
            by_category[category]["pass"] += 1
        else:
            verdict = "FAIL"
            by_category[category]["fail"] += 1

        line = f"[{scenario['id']}] {category} -> {verdict}"
        if verdict == "FAIL":
            line += f" ({reason})"
        print(line)
        report_lines.append(f"**Verdict: {verdict}**\n\n")
        if verdict == "FAIL":
            report_lines.append(f"Reason: {reason}\n\n")
        report_lines.append("---\n\n")

    denominator = total - logged
    pass_rate = (passed / denominator * 100) if denominator else 0.0

    print("\nSummary by category:")
    print(f"{'category':<15}{'count':>7}{'pass':>7}{'fail':>7}{'logged':>8}")
    for category, counts in sorted(by_category.items()):
        print(
            f"{category:<15}{counts['count']:>7}{counts['pass']:>7}{counts['fail']:>7}{counts['logged']:>8}"
        )

    print(f"\nPass rate: {passed}/{denominator} scenarios ({pass_rate:.1f}%), excluding {logged} logged (strict: false) scenario(s).")

    report_lines.append("## Summary\n\n")
    report_lines.append(f"Backend: {tool_loop.TOOL_BACKEND}\n\n")
    report_lines.append(f"Pass rate: {passed}/{denominator} ({pass_rate:.1f}%), excluding {logged} logged scenario(s).\n\n")
    report_lines.append("| category | count | pass | fail | logged |\n")
    report_lines.append("|---|---|---|---|---|\n")
    for category, counts in sorted(by_category.items()):
        report_lines.append(
            f"| {category} | {counts['count']} | {counts['pass']} | {counts['fail']} | {counts['logged']} |\n"
        )

    with open(report_path, "w") as f:
        f.writelines(report_lines)

    print(f"\nWrote {report_path}")


if __name__ == "__main__":
    main()
