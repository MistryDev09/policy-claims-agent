import importlib.util
import json
import os

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS_SCHEMA_PATH = os.path.join(REPO_ROOT, "agent", "tools_schema.json")
GATEWAY_SCHEMA_PATH = os.path.join(REPO_ROOT, "agent", "gateway_schema.json")

GATEWAY_TOOL_NAMES = {"calculate_premium_estimate", "check_claim_eligibility"}


def _load_build_schema_module():
    path = os.path.join(REPO_ROOT, "agent", "build_schema.py")
    spec = importlib.util.spec_from_file_location("build_schema_for_gateway_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def build_schema_module():
    return _load_build_schema_module()


@pytest.fixture(scope="session")
def tools_schema():
    with open(TOOLS_SCHEMA_PATH) as f:
        return json.load(f)


@pytest.fixture(scope="session")
def gateway_schema():
    with open(GATEWAY_SCHEMA_PATH) as f:
        return json.load(f)


def _tools_schema_tool(tools_schema, name):
    for tool in tools_schema["tools"]:
        if tool["toolSpec"]["name"] == name:
            return tool["toolSpec"]
    raise KeyError(name)


def _gateway_tool(gateway_schema, name):
    for tool in gateway_schema:
        if tool["name"] == name:
            return tool
    raise KeyError(name)


def test_gateway_schema_is_a_list_of_exactly_the_two_lambda_tools(gateway_schema):
    names = {tool["name"] for tool in gateway_schema}
    assert names == GATEWAY_TOOL_NAMES


def test_gateway_schema_entries_have_name_description_inputschema_only(gateway_schema):
    for tool in gateway_schema:
        assert set(tool) == {"name", "description", "inputSchema"}


def test_gateway_tool_names_are_unprefixed(gateway_schema):
    for tool in gateway_schema:
        assert "___" not in tool["name"]


def test_no_enum_key_anywhere_in_gateway_schema(gateway_schema):
    dumped = json.dumps(gateway_schema)
    assert '"enum"' not in dumped


def test_no_additionalproperties_key_anywhere_in_gateway_schema(gateway_schema):
    dumped = json.dumps(gateway_schema)
    assert '"additionalProperties"' not in dumped


def test_no_description_refers_to_this_enum(gateway_schema):
    dumped = json.dumps(gateway_schema).lower()
    assert "this enum" not in dumped


@pytest.mark.parametrize("tool_name", sorted(GATEWAY_TOOL_NAMES))
def test_property_names_match_tools_schema_for_same_tool(tools_schema, gateway_schema, tool_name):
    tools_schema_props = set(_tools_schema_tool(tools_schema, tool_name)["inputSchema"]["json"]["properties"])
    gateway_props = set(_gateway_tool(gateway_schema, tool_name)["inputSchema"]["properties"])
    assert gateway_props == tools_schema_props


@pytest.mark.parametrize("tool_name", sorted(GATEWAY_TOOL_NAMES))
def test_required_lists_match_tools_schema_for_same_tool(tools_schema, gateway_schema, tool_name):
    tools_schema_required = set(_tools_schema_tool(tools_schema, tool_name)["inputSchema"]["json"]["required"])
    gateway_required = set(_gateway_tool(gateway_schema, tool_name)["inputSchema"]["required"])
    assert gateway_required == tools_schema_required


def test_coverage_type_allowed_values_spelled_out_in_words(gateway_schema, build_schema_module):
    tool = _gateway_tool(gateway_schema, "calculate_premium_estimate")
    description = tool["inputSchema"]["properties"]["coverage_type"]["description"]
    for value in build_schema_module.coverage_type_enum():
        assert value in description


def test_claim_type_allowed_values_spelled_out_in_words(gateway_schema, build_schema_module):
    tool = _gateway_tool(gateway_schema, "check_claim_eligibility")
    description = tool["inputSchema"]["properties"]["claim_type"]["description"]
    for value in build_schema_module.claim_type_enum():
        assert value in description


def test_sub_limit_category_allowed_values_spelled_out_in_words(gateway_schema, build_schema_module):
    tool = _gateway_tool(gateway_schema, "check_claim_eligibility")
    description = tool["inputSchema"]["properties"]["sub_limit_category"]["description"]
    for value in build_schema_module.sub_limit_category_enum():
        assert value in description


def test_exclusion_code_description_does_not_enumerate_all_64_but_gives_a_hint(gateway_schema, build_schema_module):
    tool = _gateway_tool(gateway_schema, "check_claim_eligibility")
    description = tool["inputSchema"]["properties"]["exclusion_code"]["description"]
    all_codes = build_schema_module.exclusion_code_enum()
    assert len(all_codes) > 20  # sanity: this really is the big enum
    codes_present = [code for code in all_codes if code in description]
    assert len(codes_present) < len(all_codes)
    assert "UNLICENSED_DRIVER" in description
    assert "differ per policy" in description.lower()


def test_tools_schema_json_content_is_unchanged_by_gateway_work(build_schema_module):
    with open(TOOLS_SCHEMA_PATH) as f:
        committed = f.read()
    assert build_schema_module.render() == committed


def test_regenerating_gateway_schema_is_byte_identical(build_schema_module):
    with open(GATEWAY_SCHEMA_PATH) as f:
        committed = f.read()
    assert build_schema_module.render_gateway() == committed
