"""
Talks to an AgentCore Gateway over MCP: fetches and caches an OAuth2
client-credentials token from Cognito, then sends JSON-RPC tools/call
requests to the gateway's MCP endpoint. Kept separate from tool_loop.py
so the token cache, the HTTP call and the gateway's error shapes can be
read and tested on their own, without the Bedrock/boto3 machinery
around them. This module never prints, logs, or returns a token or
client secret; on failure it reports only the exception type and a
short fixed message.
"""
import json
import urllib.error
import urllib.parse
import urllib.request

MCP_PROTOCOL_VERSION = "2025-11-25"
REQUEST_TIMEOUT_SECONDS = 30

REQUIRED_ENV_VARS = ["GATEWAY_URL", "TOKEN_URL", "CLIENT_ID", "CLIENT_SECRET", "SCOPE"]

# Refresh this many seconds before the token's real expiry, so a request
# started right at the edge doesn't get a token that expires mid-flight.
EXPIRY_MARGIN_SECONDS = 60

# Cached across calls within one process. Kept as a plain dict (not a
# class) so a test can replace it wholesale to start each test with a
# clean cache, the same pattern tool_loop.py uses for _lambda_client.
_token_cache = {"access_token": None, "expires_at": 0.0}


def _now():
    # A separate function, not time.time() inline, purely so a test can
    # monkeypatch this one name to get an injectable clock.
    import time

    return time.time()


def _http_post(url, data, headers, timeout):
    """
    The only place this module touches the network. Returns (status,
    raw_bytes) for both success and HTTP error responses, so callers
    never need to catch urllib.error.HTTPError themselves.
    """
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def _missing_env_vars(env):
    return [name for name in REQUIRED_ENV_VARS if not env.get(name)]


def _fetch_token(env):
    body = urllib.parse.urlencode(
        {
            "grant_type": "client_credentials",
            "client_id": env["CLIENT_ID"],
            "client_secret": env["CLIENT_SECRET"],
            "scope": env["SCOPE"],
        }
    ).encode("utf-8")
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    status, raw = _http_post(env["TOKEN_URL"], body, headers, REQUEST_TIMEOUT_SECONDS)
    payload = json.loads(raw)
    return payload["access_token"], payload["expires_in"]


def _get_token(env, force_refresh=False):
    cache_is_fresh = (
        not force_refresh
        and _token_cache["access_token"] is not None
        and _now() < _token_cache["expires_at"] - EXPIRY_MARGIN_SECONDS
    )
    if cache_is_fresh:
        return _token_cache["access_token"]

    access_token, expires_in = _fetch_token(env)
    _token_cache["access_token"] = access_token
    _token_cache["expires_at"] = _now() + expires_in
    return access_token


def _post_tools_call(gateway_url, token, prefixed_name, arguments):
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": prefixed_name, "arguments": arguments},
        }
    ).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
    }
    return _http_post(gateway_url, body, headers, REQUEST_TIMEOUT_SECONDS)


def _parse_gateway_response(raw):
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        return {"error": {"gateway": "gateway returned a response that was not valid JSON"}}

    if payload.get("error") is not None:
        message = payload["error"].get("message", "gateway returned a JSON-RPC error")
        return {"error": {"gateway": str(message)}}

    result = payload.get("result", {})
    if result.get("isError"):
        return {"error": {"gateway": "gateway reported isError true"}}

    text = None
    for block in result.get("content", []):
        if block.get("type") == "text":
            text = block.get("text")
            break
    if text is None:
        return {"error": {"gateway": "gateway response had no text content"}}

    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return {"error": {"gateway": "gateway text content was not valid JSON"}}


def call_tool(prefixed_name, arguments, env):
    """
    The one entry point tool_loop.py calls. Never raises: any failure,
    from a missing env var to a network error to a malformed gateway
    reply, comes back as {"error": {"gateway": "<short message>"}},
    the same error-dict shape dispatch() already expects from the
    local and lambda backends.
    """
    missing = _missing_env_vars(env)
    if missing:
        return {"error": {"gateway": "missing required environment variable(s): " + ", ".join(missing)}}

    try:
        token = _get_token(env)
        status, raw = _post_tools_call(env["GATEWAY_URL"], token, prefixed_name, arguments)

        if status == 401:
            token = _get_token(env, force_refresh=True)
            status, raw = _post_tools_call(env["GATEWAY_URL"], token, prefixed_name, arguments)

        if status == 401:
            return {"error": {"gateway": "unauthorized after refreshing the token"}}

        return _parse_gateway_response(raw)
    except Exception as e:  # noqa: BLE001 - must never crash the caller, and must never leak request details
        return {"error": {"gateway": f"{type(e).__name__}: request to the gateway failed"}}
