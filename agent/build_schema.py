"""
Generates agent/tools_schema.json — the Bedrock Converse API toolConfig
for the three tools the Day 4 agent loop will call. All enums are
computed from data/policies.json and data/rate_table.json at generation
time so they can never drift out of sync with the underlying data.
"""
import json
import os
from collections import Counter

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(BASE_DIR)

with open(os.path.join(REPO_ROOT, "data", "policies.json")) as f:
    POLICIES = json.load(f)

with open(os.path.join(REPO_ROOT, "data", "rate_table.json")) as f:
    RATE_TABLE = json.load(f)

# All description text lives here, one dict keyed by tool name, so the
# wording can be reviewed/edited in one place without touching the
# schema-assembly logic below. "_tool" is the toolSpec-level description;
# every other key is a property description for that tool.
DESCRIPTIONS = {
    "calculate_premium_estimate": {
        "_tool": (
            "Estimates a monthly premium from a fixed rate table. Never calculate "
            "premiums yourself; always call this tool and report its premium_estimate "
            "and breakdown exactly. Only life, critical_illness, disability, and "
            "funeral policies can be rated. For any other product, such as pet, "
            "motor, home, travel, device, or legal, do not call this tool; tell the "
            "user that premium estimates are not available for that product. If the "
            "tool returns an error, read the error fields, fix the input or ask the "
            "user for the missing detail, then retry."
        ),
        "age": (
            "The person's age in whole years. If the user gives a fractional age, "
            "pass it as given; the tool uses age last birthday and reports the age "
            "it actually used."
        ),
        "coverage_amount": "The requested coverage amount in South African rand (ZAR).",
        "coverage_type": "The type of policy to rate. Only the values in this enum can be rated.",
        "risk_factors": (
            "Boolean risk factors relevant to the coverage type. Only include a "
            "factor the user actually stated; never assume true or false for "
            "anything they did not mention."
        ),
    },
    "check_claim_eligibility": {
        "_tool": (
            "Checks a claim against one policy using fixed rules and returns "
            "eligible, approved_amount, and a reason. Never decide eligibility or "
            "amounts yourself; relay the tool's result and reason. Amounts are in "
            "South African rand (ZAR). If the tool returns an error, read the error "
            "fields, ask the user for what is missing, or retry with corrected "
            "values. Do not tell the user the claim is eligible or denied when the "
            "tool returned an error."
        ),
        "policy_id": (
            "The exact policy ID the user gave, in the format POL-0000. If the user "
            "has not given one, ask for it."
        ),
        "claim_type": (
            "The type of coverage the claim is being made under. Must match the "
            "policy's own coverage type."
        ),
        "claim_amount": "The amount being claimed, in South African rand (ZAR).",
        "claim_date": (
            "The date of the claim, in YYYY-MM-DD format. Use today's date from the "
            "system prompt unless the user says otherwise; never invent a date."
        ),
        "diagnosis_date": (
            "The date a condition was diagnosed, in YYYY-MM-DD format. Ask the user "
            "for it on every critical_illness claim; do not guess it or reuse the "
            "claim date."
        ),
        "claim_subtype": (
            "The specific type of incident, such as collision, fire, or theft. Ask "
            "the user for it on third-party, fire, and theft motor claims."
        ),
        "exclusion_code": (
            "A specific policy exclusion that applies to this claim. Pass it only "
            "when the user states facts that clearly match a specific exclusion, "
            "never speculatively. Valid codes differ per policy; if the tool "
            "returns an error listing valid values, pick from that list or drop "
            "this field."
        ),
        "sub_limit_category": (
            "The specific sub-limited item the claim is for, such as contents, "
            "child, or windscreen. Valid values differ per policy; if the tool "
            "returns an error listing valid values, retry with one of those."
        ),
        "disability_onset_date": (
            "For disability claims with a deferred period, the date the disability "
            "began, in YYYY-MM-DD format, if the user has stated it."
        ),
    },
    "search_policy_documents": {
        "_tool": (
            "Searches the synthetic policy documents and returns text chunks with "
            "their source file. Use it for questions about what a policy covers, "
            "its exclusions, waiting periods, limits, and definitions. Do not use "
            "it for premium numbers or claim decisions. Phrase the query around the "
            "coverage type and topic, not the policy ID; a policy ID in the query "
            "makes retrieval worse. Each result includes a source file name, such "
            "as POL-0006.txt; if the user asked about a specific policy and that "
            "file is not among the results, say so rather than answering from a "
            "different policy's text. A high score does not mean the text answers "
            "the question; read it, and never fill gaps from general insurance "
            "knowledge."
        ),
        "query": "A short natural language search query about the coverage type and topic, without a policy ID.",
    },
}


def coverage_type_enum():
    # rate_table.json's own keys, minus the "_note" metadata key.
    return sorted(k for k in RATE_TABLE if not k.startswith("_"))


def risk_factor_properties():
    # Union of every coverage type's risk_multipliers keys.
    names = set()
    for coverage_type in coverage_type_enum():
        names.update(RATE_TABLE[coverage_type]["risk_multipliers"])
    return {name: {"type": "boolean"} for name in sorted(names)}


def claim_type_enum():
    return sorted({p["coverage_type"] for p in POLICIES})


def exclusion_code_enum():
    codes = set()
    for p in POLICIES:
        codes.update(p.get("exclusion_codes", []))
    return sorted(codes)


def sub_limit_category_enum():
    categories = set()
    for p in POLICIES:
        categories.update(p.get("sub_limits", {}))
    return sorted(categories)


def duplicated_sub_limit_categories():
    # Categories that appear on more than one policy — informational
    # only, the enum itself stays a flat union regardless.
    counts = Counter()
    for p in POLICIES:
        # .update() on a dict sums its VALUES as counts, not 1-per-key —
        # pass .keys() explicitly so each policy contributes 1 per
        # category it has, regardless of that category's rand amount.
        counts.update(p.get("sub_limits", {}).keys())
    return sorted(name for name, count in counts.items() if count > 1)


def build_schema():
    descriptions = DESCRIPTIONS
    return {
        "tools": [
            {
                "toolSpec": {
                    "name": "calculate_premium_estimate",
                    "description": descriptions["calculate_premium_estimate"]["_tool"],
                    "inputSchema": {
                        "json": {
                            "type": "object",
                            "properties": {
                                "age": {
                                    "type": "number",
                                    "description": descriptions["calculate_premium_estimate"]["age"],
                                },
                                "coverage_amount": {
                                    "type": "number",
                                    "description": descriptions["calculate_premium_estimate"]["coverage_amount"],
                                },
                                "coverage_type": {
                                    "type": "string",
                                    "enum": coverage_type_enum(),
                                    "description": descriptions["calculate_premium_estimate"]["coverage_type"],
                                },
                                "risk_factors": {
                                    "type": "object",
                                    "properties": risk_factor_properties(),
                                    "additionalProperties": False,
                                    "description": descriptions["calculate_premium_estimate"]["risk_factors"],
                                },
                            },
                            "required": ["age", "coverage_amount", "coverage_type"],
                        }
                    },
                }
            },
            {
                "toolSpec": {
                    "name": "check_claim_eligibility",
                    "description": descriptions["check_claim_eligibility"]["_tool"],
                    "inputSchema": {
                        "json": {
                            "type": "object",
                            "properties": {
                                "policy_id": {
                                    "type": "string",
                                    "description": descriptions["check_claim_eligibility"]["policy_id"],
                                },
                                "claim_type": {
                                    "type": "string",
                                    "enum": claim_type_enum(),
                                    "description": descriptions["check_claim_eligibility"]["claim_type"],
                                },
                                "claim_amount": {
                                    "type": "number",
                                    "description": descriptions["check_claim_eligibility"]["claim_amount"],
                                },
                                "claim_date": {
                                    "type": "string",
                                    "description": descriptions["check_claim_eligibility"]["claim_date"],
                                },
                                "diagnosis_date": {
                                    "type": "string",
                                    "description": descriptions["check_claim_eligibility"]["diagnosis_date"],
                                },
                                "claim_subtype": {
                                    "type": "string",
                                    "description": descriptions["check_claim_eligibility"]["claim_subtype"],
                                },
                                "exclusion_code": {
                                    "type": "string",
                                    "enum": exclusion_code_enum(),
                                    "description": descriptions["check_claim_eligibility"]["exclusion_code"],
                                },
                                "sub_limit_category": {
                                    "type": "string",
                                    "enum": sub_limit_category_enum(),
                                    "description": descriptions["check_claim_eligibility"]["sub_limit_category"],
                                },
                                "disability_onset_date": {
                                    "type": "string",
                                    "description": descriptions["check_claim_eligibility"]["disability_onset_date"],
                                },
                            },
                            "required": ["policy_id", "claim_type", "claim_amount", "claim_date"],
                        }
                    },
                }
            },
            {
                "toolSpec": {
                    "name": "search_policy_documents",
                    "description": descriptions["search_policy_documents"]["_tool"],
                    "inputSchema": {
                        "json": {
                            "type": "object",
                            "properties": {
                                "query": {
                                    "type": "string",
                                    "description": descriptions["search_policy_documents"]["query"],
                                },
                            },
                            "required": ["query"],
                            "additionalProperties": False,
                        }
                    },
                }
            },
        ]
    }


def render():
    # One fixed serialization call, reused by both __main__ (writes the
    # file) and the test suite (regenerate-and-diff), so "byte-identical"
    # never depends on two different formatting choices agreeing by luck.
    return json.dumps(build_schema(), indent=2, sort_keys=False) + "\n"


if __name__ == "__main__":
    output_path = os.path.join(BASE_DIR, "tools_schema.json")
    with open(output_path, "w") as f:
        f.write(render())

    print(f"Wrote {output_path}")
    print(f"exclusion_code enum size: {len(exclusion_code_enum())}")
    print(f"sub_limit_category enum size: {len(sub_limit_category_enum())}")
    print(f"sub_limit_category values on more than one policy: {duplicated_sub_limit_categories()}")
