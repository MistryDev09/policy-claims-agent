"""
Bedrock Converse API tool-use loop for the insurance agent. No AWS
client is created at import time (only inside functions), so this
module can be imported by tests without any credentials configured.
"""
import json
import os
import sys
from datetime import date

REGION = "eu-west-1"
MODEL_ID = "eu.anthropic.claude-sonnet-4-6"
KB_ID = "3VPWHXL63S"
MAX_ITERATIONS = 6
KB_RESULTS = 8

# "local" calls the two Lambda handlers as plain Python functions (the
# default, no AWS needed). "lambda" routes them through a real deployed
# Lambda via boto3 invoke() instead. Reading an env var is not an AWS
# call, so this is safe to evaluate at import time.
TOOL_BACKEND = os.environ.get("TOOL_BACKEND", "local")

FUNCTION_NAMES = {
    "calculate_premium_estimate": "sanlam-calculate-premium",
    "check_claim_eligibility": "sanlam-check-eligibility",
}

# Lazily created and cached: only ever instantiated the first time a
# lambda-backed dispatch actually happens, never at import time, same
# rule as the "no AWS client at import time" note above.
_lambda_client = None

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(BASE_DIR)

# cli_demo.py's _load_handler already does exactly what dispatch() needs
# (load a Lambda handler by file path, no package imports involved),
# reuse it instead of writing a second copy of the same three lines.
sys.path.insert(0, REPO_ROOT)
from cli_demo import _load_handler  # noqa: E402

with open(os.path.join(BASE_DIR, "tools_schema.json")) as f:
    TOOL_CONFIG = json.load(f)


def build_system_prompt():
    """
    Plain-words rules for the model, not enforced in code: the tools
    themselves are the real guardrail (they validate/reject bad input),
    this is guidance for how the model should behave around them.
    """
    today = date.today().isoformat()
    return (
        f"Today's date is {today}. "
        "You are an insurance assistant with three tools: "
        "calculate_premium_estimate, check_claim_eligibility, and "
        "search_policy_documents. Never do arithmetic yourself and never "
        "decide a premium, an eligibility outcome, or an approved amount "
        "yourself; always call the matching tool and relay its result "
        "exactly. All amounts are in South African rand (ZAR). If a "
        "required detail is missing, ask the user for it instead of "
        "guessing or assuming a value. If search_policy_documents does not "
        "return text that answers the question, say the documents do not "
        "cover it rather than answering from general knowledge. If "
        "check_claim_eligibility returns a claim_type error naming the "
        "policy's actual coverage type, retry the call with that type "
        "instead of asking the user. Only ask the user which type of "
        "cover they meant if they say outright that they want a "
        "different product than the policy covers. When you call both "
        "check_claim_eligibility and search_policy_documents in the "
        "same turn, phrase the search query from the user's own words "
        "about the product, such as home insurance, never from a "
        "claim_type you guessed. If you had to search before you knew "
        "the policy's real coverage type, and check_claim_eligibility "
        "later corrects that type, run search_policy_documents again "
        "with the corrected coverage type included in the query (for "
        "example, home insurance theft waiting period), since the "
        "first search without that term may have missed the right "
        "document. If any tool returns an error, do not state whether "
        "the claim is eligible or what the premium is; instead read "
        "the error fields and ask the user for the missing or "
        "corrected detail."
    )


def _search_policy_documents(tool_input, kb_client):
    query = tool_input.get("query")
    response = kb_client.retrieve(
        knowledgeBaseId=KB_ID,
        retrievalQuery={"text": query},
        retrievalConfiguration={"vectorSearchConfiguration": {"numberOfResults": KB_RESULTS}},
    )
    results = response.get("retrievalResults", [])
    if not results:
        return {"results": [], "note": "no documents found"}
    # Drop the score entirely (see PROGRESS.md: not usable as a
    # relevance signal for this KB) and reduce the S3 URI to just the
    # filename, e.g. "s3://bucket/policies/POL-0006.txt" -> "POL-0006.txt".
    return {
        "results": [
            {
                "source": os.path.basename(r["location"]["s3Location"]["uri"]),
                "text": r["content"]["text"],
            }
            for r in results
        ]
    }


def _get_lambda_client():
    global _lambda_client
    if _lambda_client is None:
        import boto3

        _lambda_client = boto3.client("lambda", region_name=REGION)
    return _lambda_client


def _invoke_lambda(function_name, tool_input):
    client = _get_lambda_client()
    response = client.invoke(
        FunctionName=function_name,
        Payload=json.dumps(tool_input).encode("utf-8"),
    )
    payload = json.loads(response["Payload"].read())
    if "FunctionError" in response:
        # The handler itself raised inside Lambda: payload is whatever
        # AWS reports about that crash, not a normal handler result, so
        # it gets wrapped as an error the same way dispatch() wraps a
        # local exception, not returned as-is.
        return {"error": {"lambda": payload}}
    return payload


def dispatch(name, tool_input, kb_client=None):
    """
    The ONE place tool execution happens, later this becomes a
    lambda.invoke() or an MCP call per tool, without touching run_turn.
    TOOL_BACKEND picks whether the two Lambda-backed tools run as local
    Python functions (default) or as real deployed Lambda invocations.
    search_policy_documents and the unknown-tool fallback are always
    local, the backend switch only applies to the two named functions.
    """
    if name in FUNCTION_NAMES and TOOL_BACKEND == "lambda":
        return _invoke_lambda(FUNCTION_NAMES[name], tool_input)
    if name == "calculate_premium_estimate":
        handler = _load_handler("calculate_premium", "calculate_premium.py")
        return handler(tool_input, None)
    if name == "check_claim_eligibility":
        handler = _load_handler("check_eligibility", "check_eligibility.py")
        return handler(tool_input, None)
    if name == "search_policy_documents":
        return _search_policy_documents(tool_input, kb_client)
    return {"error": {"tool": f"unknown tool {name}"}}


def run_turn(messages, client=None, kb_client=None):
    """
    Drives one user turn to completion, running as many tool_use rounds
    as needed (capped at MAX_ITERATIONS). Mutates `messages` in place,
    the caller keeps the same list across turns for multi-turn chat.
    Returns (final_text, trace); trace is a list of
    {"tool", "input", "result", "status"} in call order.
    """
    trace = []
    system_prompt = build_system_prompt()

    for _ in range(MAX_ITERATIONS):
        response = client.converse(
            modelId=MODEL_ID,
            messages=messages,
            system=[{"text": system_prompt}],
            toolConfig=TOOL_CONFIG,
            inferenceConfig={"maxTokens": 1024},
        )
        output_message = response["output"]["message"]
        messages.append(output_message)
        stop_reason = response["stopReason"]

        if stop_reason == "tool_use":
            # A single model turn can request several tools at once, all
            # of them must be answered together, in one user message, or
            # the next converse() call is malformed.
            tool_result_blocks = []
            for block in output_message["content"]:
                if "toolUse" not in block:
                    continue
                tool_use = block["toolUse"]
                name = tool_use["name"]
                tool_input = tool_use["input"]

                try:
                    result = dispatch(name, tool_input, kb_client=kb_client)
                except Exception as e:  # noqa: BLE001 - must never crash the loop
                    result = {"error": {"type": type(e).__name__, "message": str(e)}}

                status = "error" if result.get("error") is not None else "success"
                trace.append({"tool": name, "input": tool_input, "result": result, "status": status})
                tool_result_blocks.append(
                    {
                        "toolResult": {
                            "toolUseId": tool_use["toolUseId"],
                            "content": [{"json": result}],
                            "status": status,
                        }
                    }
                )
            messages.append({"role": "user", "content": tool_result_blocks})
            continue

        if stop_reason == "end_turn":
            final_text = "".join(block["text"] for block in output_message["content"] if "text" in block)
            return final_text, trace

        # Anything else (max_tokens, content_filtered, guardrail_intervened,
        # ...) is a real stop, but not one we can silently treat as done.
        return f"Model stopped with stopReason={stop_reason!r} before finishing.", trace

    return f"Reached the {MAX_ITERATIONS}-iteration cap without a final answer.", trace


def chat():
    import boto3

    client = boto3.client("bedrock-runtime", region_name=REGION)
    kb_client = boto3.client("bedrock-agent-runtime", region_name=REGION)

    print("Sanlam insurance agent (Ctrl-D or 'quit' to exit).")
    messages = []
    while True:
        try:
            user_text = input("\nYou: ")
        except EOFError:
            print()
            break
        if user_text.strip().lower() == "quit":
            break
        if not user_text.strip():
            continue

        messages.append({"role": "user", "content": [{"text": user_text}]})
        final_text, trace = run_turn(messages, client=client, kb_client=kb_client)
        for t in trace:
            print(f"  [tool] {t['tool']} {t['input']}")
        print(f"Agent: {final_text}")


if __name__ == "__main__":
    chat()
