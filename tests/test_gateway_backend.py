import importlib.util
import json
import os

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Fake values that are recognisable in a failure diff but are not real
# secrets, used to prove nothing sensitive ever leaks into a returned
# dict, a trace entry or an exception message.
FAKE_TOKEN = "FAKE-TOKEN-abc123"
FAKE_SECRET = "FAKE-SECRET-xyz789"

FAKE_ENV = {
    "GATEWAY_URL": "https://fake-gateway.example.com/mcp",
    "TOKEN_URL": "https://fake-domain.auth.eu-west-1.amazoncognito.com/oauth2/token",
    "CLIENT_ID": "fake-client-id",
    "CLIENT_SECRET": FAKE_SECRET,
    "SCOPE": "fake-resource/fake-scope",
}


def _load_module(name, relpath):
    path = os.path.join(REPO_ROOT, relpath)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def gateway_client():
    # Fresh module per test so the module-level token cache never leaks
    # between tests.
    return _load_module("gateway_client", os.path.join("agent", "gateway_client.py"))


@pytest.fixture()
def tool_loop(monkeypatch):
    monkeypatch.setenv("TOOL_BACKEND", "gateway")
    return _load_module("tool_loop_gateway", os.path.join("agent", "tool_loop.py"))


def _token_response(access_token=FAKE_TOKEN, expires_in=3600):
    return 200, json.dumps({"access_token": access_token, "expires_in": expires_in}).encode("utf-8")


def _gateway_ok_response(result_dict):
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {"isError": False, "content": [{"type": "text", "text": json.dumps(result_dict)}]},
    }
    return 200, json.dumps(body).encode("utf-8")


class ScriptedHttp:
    """Returns scripted (status, raw_bytes) responses in order, records every call."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, data, headers, timeout):
        self.calls.append({"url": url, "data": data, "headers": headers, "timeout": timeout})
        return self.responses.pop(0)


# --- (a) name mapping ---


def test_dispatch_maps_model_facing_names_to_gateway_names(tool_loop, gateway_client, monkeypatch):
    calls = []

    def fake_call_tool(prefixed_name, arguments, env):
        calls.append(prefixed_name)
        return {"ok": True}

    monkeypatch.setattr(tool_loop.gateway_client, "call_tool", fake_call_tool)
    tool_loop.dispatch("calculate_premium_estimate", {"age": 35})
    tool_loop.dispatch("check_claim_eligibility", {"policy_id": "POL-0005"})

    assert calls == [
        "calculate-premium___calculate_premium_estimate",
        "check-eligibility___check_claim_eligibility",
    ]


# --- (b) JSON-RPC request shape ---


def test_gateway_request_is_jsonrpc_tools_call_with_required_headers(gateway_client):
    http = ScriptedHttp([_token_response(), _gateway_ok_response({"premium_estimate": 487.5})])
    gateway_client._http_post = http

    gateway_client.call_tool("calculate-premium___calculate_premium_estimate", {"age": 35}, FAKE_ENV)

    gateway_call = http.calls[-1]
    body = json.loads(gateway_call["data"])
    assert body["jsonrpc"] == "2.0"
    assert body["method"] == "tools/call"
    assert body["params"] == {"name": "calculate-premium___calculate_premium_estimate", "arguments": {"age": 35}}

    headers = gateway_call["headers"]
    assert headers["Authorization"] == f"Bearer {FAKE_TOKEN}"
    assert headers["Content-Type"] == "application/json"
    assert headers["MCP-Protocol-Version"] == "2025-11-25"


# --- (c) parsed dict from content[0].text ---


def test_gateway_reply_returns_parsed_dict_from_text(gateway_client):
    http = ScriptedHttp([_token_response(), _gateway_ok_response({"premium_estimate": 487.5, "error": None})])
    gateway_client._http_post = http

    result = gateway_client.call_tool("calculate-premium___calculate_premium_estimate", {"age": 35}, FAKE_ENV)
    assert result == {"premium_estimate": 487.5, "error": None}


# --- (d) lambda-shaped error passes through as an error dict ---


def test_lambda_error_shape_in_text_becomes_error_result(gateway_client):
    lambda_error_payload = {"error": {"claim_type": "policy POL-0006 is a home policy, not motor"}}
    http = ScriptedHttp([_token_response(), _gateway_ok_response(lambda_error_payload)])
    gateway_client._http_post = http

    result = gateway_client.call_tool("check-eligibility___check_claim_eligibility", {}, FAKE_ENV)
    assert result == lambda_error_payload
    assert result["error"] is not None


# --- (e) isError true / top-level JSON-RPC error / non-JSON text never raise ---


def test_is_error_true_returns_gateway_error_dict(gateway_client):
    body = {"jsonrpc": "2.0", "id": 1, "result": {"isError": True, "content": [{"type": "text", "text": "boom"}]}}
    http = ScriptedHttp([_token_response(), (200, json.dumps(body).encode("utf-8"))])
    gateway_client._http_post = http

    result = gateway_client.call_tool("calculate-premium___calculate_premium_estimate", {}, FAKE_ENV)
    assert isinstance(result["error"], dict)
    assert "gateway" in result["error"]


def test_top_level_jsonrpc_error_returns_gateway_error_dict(gateway_client):
    body = {"jsonrpc": "2.0", "id": 1, "error": {"code": -32600, "message": "Unsupported protocol version"}}
    http = ScriptedHttp([_token_response(), (200, json.dumps(body).encode("utf-8"))])
    gateway_client._http_post = http

    result = gateway_client.call_tool("calculate-premium___calculate_premium_estimate", {}, FAKE_ENV)
    assert isinstance(result["error"], dict)
    assert "gateway" in result["error"]


def test_non_json_text_field_returns_gateway_error_dict_not_raise(gateway_client):
    body = {"jsonrpc": "2.0", "id": 1, "result": {"isError": False, "content": [{"type": "text", "text": "not json at all"}]}}
    http = ScriptedHttp([_token_response(), (200, json.dumps(body).encode("utf-8"))])
    gateway_client._http_post = http

    result = gateway_client.call_tool("calculate-premium___calculate_premium_estimate", {}, FAKE_ENV)
    assert isinstance(result["error"], dict)
    assert "gateway" in result["error"]


# --- (f) token caching, expiry, 401 retry ---


def test_token_is_fetched_once_and_cached_across_two_calls(gateway_client):
    http = ScriptedHttp(
        [
            _token_response(),
            _gateway_ok_response({"a": 1}),
            _gateway_ok_response({"b": 2}),
        ]
    )
    gateway_client._http_post = http

    gateway_client.call_tool("calculate-premium___calculate_premium_estimate", {}, FAKE_ENV)
    gateway_client.call_tool("calculate-premium___calculate_premium_estimate", {}, FAKE_ENV)

    token_calls = [c for c in http.calls if c["url"] == FAKE_ENV["TOKEN_URL"]]
    assert len(token_calls) == 1


def test_token_refetched_after_expiry_with_injectable_clock(gateway_client):
    fake_time = {"now": 1000.0}
    gateway_client._now = lambda: fake_time["now"]

    http = ScriptedHttp(
        [
            _token_response(expires_in=100),
            _gateway_ok_response({"a": 1}),
            _token_response(expires_in=100),
            _gateway_ok_response({"b": 2}),
        ]
    )
    gateway_client._http_post = http

    gateway_client.call_tool("calculate-premium___calculate_premium_estimate", {}, FAKE_ENV)
    # Refresh happens 60 seconds early, so just past (expires_in - 60) must refetch.
    fake_time["now"] += 41  # 1000 + 41 = 1041, expiry margin is 1000+100-60=1040
    gateway_client.call_tool("calculate-premium___calculate_premium_estimate", {}, FAKE_ENV)

    token_calls = [c for c in http.calls if c["url"] == FAKE_ENV["TOKEN_URL"]]
    assert len(token_calls) == 2


def test_401_triggers_one_refresh_and_one_retry_then_error_if_still_failing(gateway_client):
    http = ScriptedHttp(
        [
            _token_response(),
            (401, b"unauthorized"),
            _token_response(),
            (401, b"still unauthorized"),
        ]
    )
    gateway_client._http_post = http

    result = gateway_client.call_tool("calculate-premium___calculate_premium_estimate", {}, FAKE_ENV)
    token_calls = [c for c in http.calls if c["url"] == FAKE_ENV["TOKEN_URL"]]
    assert len(token_calls) == 2
    assert result["error"] is not None


def test_401_then_success_on_retry(gateway_client):
    http = ScriptedHttp(
        [
            _token_response(),
            (401, b"unauthorized"),
            _token_response(access_token="FAKE-TOKEN-refreshed"),
            _gateway_ok_response({"premium_estimate": 487.5}),
        ]
    )
    gateway_client._http_post = http

    result = gateway_client.call_tool("calculate-premium___calculate_premium_estimate", {}, FAKE_ENV)
    assert result == {"premium_estimate": 487.5}


# --- (g) missing env vars ---


def test_missing_env_vars_reports_names_only(gateway_client):
    env = {"GATEWAY_URL": "https://fake-gateway.example.com/mcp"}  # missing the other four
    result = gateway_client.call_tool("calculate-premium___calculate_premium_estimate", {}, env)

    assert result["error"] is not None
    message = result["error"]["gateway"]
    assert "TOKEN_URL" in message
    assert "CLIENT_ID" in message
    assert "CLIENT_SECRET" in message
    assert "SCOPE" in message


# --- (h) no secret ever leaks ---


def test_no_result_trace_or_exception_contains_token_or_secret(gateway_client):
    http = ScriptedHttp([_token_response(), _gateway_ok_response({"premium_estimate": 487.5})])
    gateway_client._http_post = http

    result = gateway_client.call_tool("calculate-premium___calculate_premium_estimate", {}, FAKE_ENV)
    dumped = json.dumps(result)
    assert FAKE_TOKEN not in dumped
    assert FAKE_SECRET not in dumped


def test_no_secret_leaks_even_when_gateway_call_raises(gateway_client):
    def raising_http(url, data, headers, timeout):
        raise RuntimeError(f"connection failed for token {FAKE_TOKEN} secret {FAKE_SECRET}")

    gateway_client._http_post = raising_http
    result = gateway_client.call_tool("calculate-premium___calculate_premium_estimate", {}, FAKE_ENV)

    dumped = json.dumps(result)
    assert FAKE_TOKEN not in dumped
    assert FAKE_SECRET not in dumped
    assert result["error"] is not None


# --- (i) TOOL_BACKEND validation ---


def test_default_backend_is_still_local():
    tool_loop = _load_module("tool_loop_default", os.path.join("agent", "tool_loop.py"))
    assert tool_loop.TOOL_BACKEND == "local"


def test_lambda_backend_still_accepted(monkeypatch):
    monkeypatch.setenv("TOOL_BACKEND", "lambda")
    tool_loop = _load_module("tool_loop_lambda_ok", os.path.join("agent", "tool_loop.py"))
    assert tool_loop.TOOL_BACKEND == "lambda"


def test_gateway_backend_accepted(monkeypatch):
    monkeypatch.setenv("TOOL_BACKEND", "gateway")
    tool_loop = _load_module("tool_loop_gateway_ok", os.path.join("agent", "tool_loop.py"))
    assert tool_loop.TOOL_BACKEND == "gateway"


def test_unknown_backend_raises_clear_error_at_import_not_silent_fallback(monkeypatch):
    monkeypatch.setenv("TOOL_BACKEND", "carrier-pigeon")
    with pytest.raises(Exception) as exc_info:
        _load_module("tool_loop_bad_backend", os.path.join("agent", "tool_loop.py"))
    assert "carrier-pigeon" in str(exc_info.value)


# --- (j) search_policy_documents always local under all backends ---


def test_search_policy_documents_is_local_under_gateway_backend(tool_loop, monkeypatch):
    class FakeKBClient:
        def retrieve(self, **kwargs):
            return {"retrievalResults": []}

    # Never touch gateway_client for this tool, even under TOOL_BACKEND=gateway.
    def fail_call_tool(*args, **kwargs):
        raise AssertionError("search_policy_documents must never go through the gateway")

    monkeypatch.setattr(tool_loop.gateway_client, "call_tool", fail_call_tool)
    result = tool_loop.dispatch("search_policy_documents", {"query": "theft waiting period"}, kb_client=FakeKBClient())
    assert result == {"results": [], "note": "no documents found"}
