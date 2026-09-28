import importlib.util
import json
import os

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA_PATH = os.path.join(REPO_ROOT, "agent", "tools_schema.json")


def _load_build_schema_module():
    path = os.path.join(REPO_ROOT, "agent", "build_schema.py")
    spec = importlib.util.spec_from_file_location("build_schema", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def build_schema_module():
    return _load_build_schema_module()


@pytest.fixture(scope="session")
def schema():
    with open(SCHEMA_PATH) as f:
        return json.load(f)


@pytest.fixture(scope="session")
def rate_table():
    with open(os.path.join(REPO_ROOT, "data", "rate_table.json")) as f:
        return json.load(f)


def _tool_by_name(schema, name):
    for tool in schema["tools"]:
        if tool["toolSpec"]["name"] == name:
            return tool["toolSpec"]
    raise KeyError(name)


def test_schema_parses_with_exactly_three_tools(schema):
    names = {tool["toolSpec"]["name"] for tool in schema["tools"]}
    assert names == {
        "calculate_premium_estimate",
        "check_claim_eligibility",
        "search_policy_documents",
    }


def test_coverage_type_enum_matches_rate_table(schema, rate_table):
    expected = sorted(k for k in rate_table if not k.startswith("_"))
    tool = _tool_by_name(schema, "calculate_premium_estimate")
    actual = tool["inputSchema"]["json"]["properties"]["coverage_type"]["enum"]
    assert actual == expected


def test_risk_factor_properties_match_rate_table_union(schema, rate_table):
    expected = set()
    for coverage_type, data in rate_table.items():
        if coverage_type.startswith("_"):
            continue
        expected.update(data["risk_multipliers"])
    tool = _tool_by_name(schema, "calculate_premium_estimate")
    actual_props = tool["inputSchema"]["json"]["properties"]["risk_factors"]["properties"]
    assert set(actual_props) == expected
    assert all(p["type"] == "boolean" for p in actual_props.values())


def test_claim_type_enum_matches_policies_coverage_types(schema, policies):
    expected = sorted({p["coverage_type"] for p in policies.values()})
    tool = _tool_by_name(schema, "check_claim_eligibility")
    actual = tool["inputSchema"]["json"]["properties"]["claim_type"]["enum"]
    assert actual == expected


def test_exclusion_code_enum_matches_policies_union(schema, policies):
    expected = set()
    for p in policies.values():
        expected.update(p.get("exclusion_codes", []))
    tool = _tool_by_name(schema, "check_claim_eligibility")
    actual = tool["inputSchema"]["json"]["properties"]["exclusion_code"]["enum"]
    assert sorted(actual) == sorted(expected)


def test_sub_limit_category_enum_matches_policies_union(schema, policies):
    expected = set()
    for p in policies.values():
        expected.update(p.get("sub_limits", {}))
    tool = _tool_by_name(schema, "check_claim_eligibility")
    actual = tool["inputSchema"]["json"]["properties"]["sub_limit_category"]["enum"]
    assert sorted(actual) == sorted(expected)


REQUIRED_BY_TOOL = {
    "calculate_premium_estimate": {"age", "coverage_amount", "coverage_type"},
    "check_claim_eligibility": {"policy_id", "claim_type", "claim_amount", "claim_date"},
    "search_policy_documents": {"query"},
}


@pytest.mark.parametrize("tool_name, expected_required", REQUIRED_BY_TOOL.items())
def test_required_lists_match_spec(schema, tool_name, expected_required):
    tool = _tool_by_name(schema, tool_name)
    assert set(tool["inputSchema"]["json"]["required"]) == expected_required


def test_no_description_is_empty_or_contains_todo(schema):
    for tool in schema["tools"]:
        spec = tool["toolSpec"]
        assert spec["description"].strip()
        assert "TODO" not in spec["description"]
        for prop_name, prop in spec["inputSchema"]["json"]["properties"].items():
            description = prop.get("description", "")
            assert description.strip(), f"{spec['name']}.{prop_name} has an empty description"
            assert "TODO" not in description, f"{spec['name']}.{prop_name} contains TODO"


def test_regenerating_schema_is_byte_identical(build_schema_module):
    with open(SCHEMA_PATH) as f:
        committed = f.read()
    assert build_schema_module.render() == committed
