import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read_bytes(*parts):
    with open(os.path.join(REPO_ROOT, *parts), "rb") as f:
        return f.read()


def test_calculate_premium_rate_table_matches_canonical_data():
    bundled = _read_bytes("lambdas", "calculate_premium", "rate_table.json")
    canonical = _read_bytes("data", "rate_table.json")
    assert bundled == canonical, "lambdas/calculate_premium/rate_table.json is out of sync with data/rate_table.json, re-copy before packaging"


def test_check_eligibility_policies_matches_canonical_data():
    bundled = _read_bytes("lambdas", "check_eligibility", "policies.json")
    canonical = _read_bytes("data", "policies.json")
    assert bundled == canonical, "lambdas/check_eligibility/policies.json is out of sync with data/policies.json, re-copy before packaging"
