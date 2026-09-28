import os
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLI_PATH = os.path.join(REPO_ROOT, "cli_demo.py")


def run_cli(*args):
    return subprocess.run(
        [sys.executable, CLI_PATH, *args],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )


def test_premium_valid_input():
    result = run_cli("--age", "34", "--coverage", "500000", "--type", "life")
    assert result.returncode == 0
    assert "Traceback" not in result.stderr
    assert "325.00" in result.stdout  # hand-computed: 500000/1000 * 0.65


def test_premium_out_of_scope_coverage_type_no_traceback():
    result = run_cli("--age", "40", "--coverage", "100000", "--type", "motor")
    assert "Traceback" not in result.stderr
    assert result.returncode != 0
    assert "coverage_type" in result.stdout


def test_check_claim_valid_policy():
    result = run_cli(
        "--check-claim", "POL-0001", "--type", "life", "--amount", "100000", "--claim-date", "2024-08-01"
    )
    assert result.returncode == 0
    assert "Traceback" not in result.stderr
    assert "Eligible" in result.stdout


def test_check_claim_fake_policy_no_traceback():
    result = run_cli(
        "--check-claim", "POL-9999", "--type", "life", "--amount", "100000", "--claim-date", "2024-01-01"
    )
    assert "Traceback" not in result.stderr
    assert result.returncode != 0
    assert "policy_id" in result.stdout


# --- Day 4 pre-work (see PROGRESS.md): "(capped)" must only print when a
# sub-limit or coverage-amount cap actually applied, not whenever
# approved_amount differs from claim_amount for any reason (excess
# deduction is a different thing and is already spelled out in the
# reason string). FAILS today.


def test_excess_only_deduction_not_labelled_capped():
    # POL-0005 has a 6,500 excess and a 320,000 coverage_amount; a 45,000
    # claim is nowhere near either cap, so the only reason approved_amount
    # differs from claim_amount is the excess. Today the CLI prints
    # "(capped)" anyway, which is misleading — nothing was capped.
    result = run_cli(
        "--check-claim", "POL-0005", "--type", "motor", "--amount", "45000", "--claim-date", "2026-05-12"
    )
    assert result.returncode == 0
    assert "Traceback" not in result.stderr
    assert "(capped)" not in result.stdout
    assert "excess" in result.stdout


def test_output_changes_with_input_not_hardcoded():
    result_a = run_cli("--age", "34", "--coverage", "500000", "--type", "life")
    result_b = run_cli(
        "--age", "50", "--coverage", "400000", "--type", "critical_illness",
        "--smoker", "--family-history",
    )
    assert result_a.stdout != result_b.stdout
    assert "1164.80" in result_b.stdout  # hand-computed: 640.0 * 1.4 * 1.3
