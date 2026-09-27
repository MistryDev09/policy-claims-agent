import importlib.util
import json
import os

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_handler(subdir, filename):
    path = os.path.join(REPO_ROOT, "lambdas", subdir, filename)
    spec = importlib.util.spec_from_file_location(filename, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.lambda_handler


@pytest.fixture(scope="session")
def calculate_premium():
    return _load_handler("calculate_premium", "calculate_premium.py")


@pytest.fixture(scope="session")
def check_eligibility():
    return _load_handler("check_eligibility", "check_eligibility.py")


@pytest.fixture(scope="session")
def policies():
    with open(os.path.join(REPO_ROOT, "data", "policies.json")) as f:
        return {p["policy_id"]: p for p in json.load(f)}


@pytest.fixture(scope="session")
def claims():
    with open(os.path.join(REPO_ROOT, "data", "claims.json")) as f:
        return json.load(f)
