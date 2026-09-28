"""
Compares the local handler against the AgentCore Gateway backend for
the same 8 fixed cases agent/verify_lambdas.py uses, plus a check that
the gateway rejects requests with no or a bad bearer token. This file
makes real network calls (an OAuth2 token request, then MCP calls to
the gateway) so it is not run by Claude, only by the person operating
this repo, after the gateway and its two Lambda targets actually
exist. It never prints a token, client secret, or gateway URL.
"""
import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import gateway_client  # noqa: E402
from verify_lambdas import CASES, call_local  # noqa: E402

GATEWAY_TOOL_NAMES = {
    "calculate_premium_estimate": "calculate-premium___calculate_premium_estimate",
    "check_claim_eligibility": "check-eligibility___check_claim_eligibility",
}

EXPECTED_TOOL_NAMES = set(GATEWAY_TOOL_NAMES.values())


def call_gateway(tool_name, tool_input):
    return gateway_client.call_tool(GATEWAY_TOOL_NAMES[tool_name], tool_input, os.environ)


def run_case_comparison():
    passed = 0
    for i, (tool_name, tool_input) in enumerate(CASES, start=1):
        local_result = call_local(tool_name, tool_input)
        gateway_result = call_gateway(tool_name, tool_input)
        ok = local_result == gateway_result

        status = "PASS" if ok else "FAIL"
        print(f"[{i}] {tool_name} {tool_input} -> {status}")
        if ok:
            passed += 1
        else:
            print(f"    local:   {local_result}")
            print(f"    gateway: {gateway_result}")

    print(f"\n{passed}/{len(CASES)} passed")


def list_gateway_tools():
    """
    A plain tools/list call (not tools/call), used only to report which
    tool names the gateway advertises, never any secret.
    """
    token = gateway_client._get_token(os.environ)
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "MCP-Protocol-Version": gateway_client.MCP_PROTOCOL_VERSION,
    }
    status, raw = gateway_client._http_post(os.environ["GATEWAY_URL"], body, headers, 30)
    payload = json.loads(raw)
    tools = payload.get("result", {}).get("tools", [])
    names = {t.get("name") for t in tools}

    print(f"\ngateway tools/list reports {len(names)} tool(s): {sorted(names)}")
    print(f"expected: {sorted(EXPECTED_TOOL_NAMES)}")
    print("MATCH" if names == EXPECTED_TOOL_NAMES else "MISMATCH")


def check_no_auth_rejected():
    """
    tools/list with no Authorization header, then with a garbage bearer
    token. Prints PASS only if both are rejected (HTTP 401/403, or a
    JSON-RPC error with no tools list); a gateway that answers either
    call with a real tool list has a broken auth check.
    """
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}).encode("utf-8")
    gateway_url = os.environ["GATEWAY_URL"]

    def _is_rejected(status, raw):
        if status in (401, 403):
            return True
        try:
            payload = json.loads(raw)
        except (ValueError, TypeError):
            return False
        return payload.get("error") is not None and not payload.get("result", {}).get("tools")

    no_auth_headers = {"Content-Type": "application/json", "MCP-Protocol-Version": gateway_client.MCP_PROTOCOL_VERSION}
    status, raw = gateway_client._http_post(gateway_url, body, no_auth_headers, 30)
    no_auth_rejected = _is_rejected(status, raw)

    garbage_headers = dict(no_auth_headers)
    garbage_headers["Authorization"] = "Bearer garbage-token-not-a-real-jwt"
    status, raw = gateway_client._http_post(gateway_url, body, garbage_headers, 30)
    garbage_token_rejected = _is_rejected(status, raw)

    print(f"\nno-auth request rejected: {no_auth_rejected}")
    print(f"garbage-token request rejected: {garbage_token_rejected}")
    print("PASS" if no_auth_rejected and garbage_token_rejected else "FAIL")


def main():
    run_case_comparison()
    list_gateway_tools()
    check_no_auth_rejected()


if __name__ == "__main__":
    main()
