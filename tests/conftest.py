import importlib.util
import json
import os

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_module(subdir, filename):
    path = os.path.join(REPO_ROOT, "lambdas", subdir, filename)
    spec = importlib.util.spec_from_file_location(filename, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def calculate_premium():
    return _load_module("calculate_premium", "calculate_premium.py").lambda_handler


@pytest.fixture(scope="session")
def check_eligibility():
    return _load_module("check_eligibility", "check_eligibility.py").lambda_handler


@pytest.fixture(scope="session")
def check_eligibility_module():
    # Returns the module itself (not just lambda_handler) so tests can
    # monkeypatch POLICIES_BY_ID with a synthetic policy — needed to
    # exercise field combinations (e.g. excess + sub_limits) that no
    # real policy in policies.json has.
    return _load_module("check_eligibility", "check_eligibility.py")


@pytest.fixture(scope="session")
def policies():
    with open(os.path.join(REPO_ROOT, "data", "policies.json")) as f:
        return {p["policy_id"]: p for p in json.load(f)}


@pytest.fixture(scope="session")
def claims():
    with open(os.path.join(REPO_ROOT, "data", "claims.json")) as f:
        return json.load(f)
