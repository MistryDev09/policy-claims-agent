import importlib.util
import os
from datetime import date

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_tool_loop():
    # Fresh module object per test file run (session-scoped fixture below
    # reuses it) — same importlib.util pattern as conftest.py's
    # _load_module, since agent/ isn't a package either.
    path = os.path.join(REPO_ROOT, "agent", "tool_loop.py")
    spec = importlib.util.spec_from_file_location("tool_loop", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def tool_loop():
    return _load_tool_loop()


class FakeConverseClient:
    """Returns scripted responses in order; records every call it got."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def converse(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


class FakeAlwaysToolUseClient:
    """Never stops — used to exercise the MAX_ITERATIONS cap."""

    def __init__(self, tool_use_response):
        self.tool_use_response = tool_use_response
        self.call_count = 0

    def converse(self, **kwargs):
        self.call_count += 1
        return self.tool_use_response


class FakeKBClient:
    def __init__(self, results):
        self.results = results

    def retrieve(self, **kwargs):
        self.last_kwargs = kwargs
        return {"retrievalResults": self.results}


def _text_block(text):
    return {"role": "assistant", "content": [{"text": text}]}


def _tool_use_message(tool_use_id, name, tool_input):
    return {
        "role": "assistant",
        "content": [{"toolUse": {"toolUseId": tool_use_id, "name": name, "input": tool_input}}],
    }


def _end_turn_response(text):
    return {"output": {"message": _text_block(text)}, "stopReason": "end_turn"}


def _tool_use_response(*tool_uses):
    # tool_uses: list of (tool_use_id, name, tool_input)
    content = [{"toolUse": {"toolUseId": tid, "name": name, "input": inp}} for tid, name, inp in tool_uses]
    return {"output": {"message": {"role": "assistant", "content": content}}, "stopReason": "tool_use"}


def test_tool_use_then_end_turn_returns_final_text_and_one_item_trace(tool_loop):
    client = FakeConverseClient(
        [
            _tool_use_response(("t1", "calculate_premium_estimate", {"age": 34, "coverage_amount": 500000, "coverage_type": "life"})),
            _end_turn_response("Your premium is R325.00/month."),
        ]
    )
    messages = [{"role": "user", "content": [{"text": "premium please"}]}]
    final_text, trace = tool_loop.run_turn(messages, client=client)

    assert final_text == "Your premium is R325.00/month."
    assert len(trace) == 1
    assert trace[0]["tool"] == "calculate_premium_estimate"
    assert trace[0]["status"] == "success"


def test_two_tool_use_blocks_produce_one_user_message_with_two_tool_results(tool_loop):
    client = FakeConverseClient(
        [
            _tool_use_response(
                ("t1", "calculate_premium_estimate", {"age": 34, "coverage_amount": 500000, "coverage_type": "life"}),
                ("t2", "calculate_premium_estimate", {"age": 40, "coverage_amount": 300000, "coverage_type": "life"}),
            ),
            _end_turn_response("Done."),
        ]
    )
    messages = [{"role": "user", "content": [{"text": "two premiums please"}]}]
    tool_loop.run_turn(messages, client=client)

    # messages[-2] is the tool_use assistant message, messages[-1] the
    # single user message carrying both toolResult blocks back.
    tool_result_message = messages[-2]
    assert tool_result_message["role"] == "user"
    assert len(tool_result_message["content"]) == 2
    ids = {block["toolResult"]["toolUseId"] for block in tool_result_message["content"]}
    assert ids == {"t1", "t2"}


def test_handler_error_dict_becomes_error_status_and_loop_continues(tool_loop):
    client = FakeConverseClient(
        [
            _tool_use_response(("t1", "calculate_premium_estimate", {"age": 34, "coverage_amount": 500000, "coverage_type": "pet"})),
            _end_turn_response("That product isn't rated by this tool."),
        ]
    )
    messages = [{"role": "user", "content": [{"text": "pet premium please"}]}]
    final_text, trace = tool_loop.run_turn(messages, client=client)

    assert trace[0]["status"] == "error"
    assert trace[0]["result"]["error"] is not None
    assert final_text == "That product isn't rated by this tool."


def test_dispatch_raising_does_not_crash_the_loop(tool_loop):
    # search_policy_documents with kb_client=None makes dispatch's
    # kb_client.retrieve(...) call raise AttributeError — a real
    # exception, not a simulated one.
    client = FakeConverseClient(
        [
            _tool_use_response(("t1", "search_policy_documents", {"query": "theft waiting period"})),
            _end_turn_response("Something went wrong looking that up."),
        ]
    )
    messages = [{"role": "user", "content": [{"text": "search please"}]}]
    final_text, trace = tool_loop.run_turn(messages, client=client, kb_client=None)

    assert trace[0]["status"] == "error"
    assert trace[0]["result"]["error"]["type"] == "AttributeError"
    assert final_text == "Something went wrong looking that up."


def test_always_tool_use_stops_at_max_iterations(tool_loop):
    tool_use_response = _tool_use_response(("t1", "calculate_premium_estimate", {"age": 34, "coverage_amount": 500000, "coverage_type": "life"}))
    client = FakeAlwaysToolUseClient(tool_use_response)
    messages = [{"role": "user", "content": [{"text": "loop forever"}]}]
    final_text, trace = tool_loop.run_turn(messages, client=client)

    assert client.call_count == tool_loop.MAX_ITERATIONS
    assert str(tool_loop.MAX_ITERATIONS) in final_text
    assert len(trace) == tool_loop.MAX_ITERATIONS


def test_dispatch_real_handlers_return_expected_values(tool_loop):
    premium_result = tool_loop.dispatch(
        "calculate_premium_estimate",
        {"age": 35, "coverage_amount": 500000, "coverage_type": "life", "risk_factors": {"smoker": True}},
    )
    assert premium_result["premium_estimate"] == 487.5

    eligibility_result = tool_loop.dispatch(
        "check_claim_eligibility",
        {"policy_id": "POL-0005", "claim_type": "motor", "claim_amount": 45000, "claim_date": "2026-09-28"},
    )
    assert eligibility_result["approved_amount"] == 38500


def test_kb_path_strips_uri_to_basename_and_drops_scores(tool_loop):
    kb_client = FakeKBClient(
        [
            {
                "score": 0.87,
                "location": {"s3Location": {"uri": "s3://sanlam-insurance-agent-devakmistry-2026/policies/POL-0006.txt"}},
                "content": {"text": "Theft waiting period: 30 days."},
            }
        ]
    )
    result = tool_loop.dispatch("search_policy_documents", {"query": "theft waiting period"}, kb_client=kb_client)

    assert result == {"results": [{"source": "POL-0006.txt", "text": "Theft waiting period: 30 days."}]}
    assert "score" not in result["results"][0]
    assert kb_client.last_kwargs["retrievalConfiguration"]["vectorSearchConfiguration"]["numberOfResults"] == tool_loop.KB_RESULTS


def test_search_with_no_results_returns_note(tool_loop):
    kb_client = FakeKBClient([])
    result = tool_loop.dispatch("search_policy_documents", {"query": "space tourism"}, kb_client=kb_client)
    assert result == {"results": [], "note": "no documents found"}


def test_system_prompt_contains_todays_date_and_claim_type_retry_rule(tool_loop):
    prompt = tool_loop.build_system_prompt()
    assert date.today().isoformat() in prompt
    # New rule: retry with the actual coverage type the tool named,
    # do not stop and ask the user first.
    assert "retry the call with that type" in prompt
    assert "actual coverage type" in prompt
    # The old rule this replaces must be gone, not just supplemented.
    assert "ask which policy or claim type they meant" not in prompt
    assert "different type of cover than they described" not in prompt


def test_system_prompt_says_to_phrase_search_query_from_users_words_not_guessed_claim_type(tool_loop):
    prompt = tool_loop.build_system_prompt()
    assert "phrase the search query from the user's own words" in prompt.lower()
    assert "never from a claim_type you guessed" in prompt.lower()


def test_system_prompt_says_to_redo_search_once_claim_type_is_corrected(tool_loop):
    # A neutral first-pass query (no product term, since the model did
    # not yet know the real coverage type) can still miss the right
    # document, per the documented retrieval trap. Once
    # check_claim_eligibility corrects the type, the model should search
    # again with that term included, not settle for the first miss.
    prompt = tool_loop.build_system_prompt()
    assert "run search_policy_documents again" in prompt.lower()
    assert "corrected coverage type included in the query" in prompt.lower()


# --- TOOL_BACKEND=lambda dispatch switch. A fake lambda client is
# monkeypatched directly onto tool_loop._lambda_client, bypassing real
# boto3 entirely, with TOOL_BACKEND monkeypatched to "lambda" so
# dispatch() takes the remote path. monkeypatch reverts both after each
# test, even though the tool_loop fixture is session-scoped.


class FakeLambdaClient:
    def __init__(self, response):
        self.response = response
        self.last_kwargs = None

    def invoke(self, **kwargs):
        self.last_kwargs = kwargs
        return self.response


def _lambda_response(payload_dict, function_error=None):
    import io
    import json as _json

    response = {"Payload": io.BytesIO(_json.dumps(payload_dict).encode("utf-8"))}
    if function_error is not None:
        response["FunctionError"] = function_error
    return response


def test_lambda_backend_sends_tool_input_as_payload(tool_loop, monkeypatch):
    fake_client = FakeLambdaClient(_lambda_response({"premium_estimate": 487.5, "breakdown": "...", "error": None}))
    monkeypatch.setattr(tool_loop, "_lambda_client", fake_client)
    monkeypatch.setattr(tool_loop, "TOOL_BACKEND", "lambda")

    tool_input = {"age": 35, "coverage_amount": 500000, "coverage_type": "life", "risk_factors": {"smoker": True}}
    tool_loop.dispatch("calculate_premium_estimate", tool_input)

    assert fake_client.last_kwargs["FunctionName"] == "sanlam-calculate-premium"
    import json as _json

    assert _json.loads(fake_client.last_kwargs["Payload"]) == tool_input


def test_lambda_backend_parses_successful_result(tool_loop, monkeypatch):
    fake_client = FakeLambdaClient(_lambda_response({"eligible": True, "approved_amount": 38500, "reason": "...", "error": None}))
    monkeypatch.setattr(tool_loop, "_lambda_client", fake_client)
    monkeypatch.setattr(tool_loop, "TOOL_BACKEND", "lambda")

    result = tool_loop.dispatch(
        "check_claim_eligibility",
        {"policy_id": "POL-0005", "claim_type": "motor", "claim_amount": 45000, "claim_date": "2026-09-28"},
    )
    assert result == {"eligible": True, "approved_amount": 38500, "reason": "...", "error": None}


def test_lambda_backend_function_error_becomes_error_result(tool_loop, monkeypatch):
    fake_client = FakeLambdaClient(
        _lambda_response({"errorType": "KeyError", "errorMessage": "boom"}, function_error="Unhandled")
    )
    monkeypatch.setattr(tool_loop, "_lambda_client", fake_client)
    monkeypatch.setattr(tool_loop, "TOOL_BACKEND", "lambda")

    result = tool_loop.dispatch("calculate_premium_estimate", {"age": 35})
    assert result["error"] == {"lambda": {"errorType": "KeyError", "errorMessage": "boom"}}


def test_default_backend_stays_local_not_lambda(tool_loop, monkeypatch):
    fake_client = FakeLambdaClient(_lambda_response({"premium_estimate": 999, "breakdown": "wrong", "error": None}))
    monkeypatch.setattr(tool_loop, "_lambda_client", fake_client)
    # TOOL_BACKEND left at its default ("local") deliberately, not patched.

    result = tool_loop.dispatch(
        "calculate_premium_estimate",
        {"age": 35, "coverage_amount": 500000, "coverage_type": "life", "risk_factors": {"smoker": True}},
    )
    assert result["premium_estimate"] == 487.5  # real local handler, not the fake's 999
    assert fake_client.last_kwargs is None  # never called
