import argparse
import importlib.util
import os
import sys
from datetime import date

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _load_handler(subdir, filename):
    path = os.path.join(BASE_DIR, "lambdas", subdir, filename)
    spec = importlib.util.spec_from_file_location(filename, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.lambda_handler


def build_parser():
    parser = argparse.ArgumentParser(
        description="Sanlam insurance agent — local CLI demo (Day 3, no AWS)."
    )

    # premium mode
    parser.add_argument("--age", type=str, help="age in years (premium mode)")
    parser.add_argument("--coverage", type=str, help="coverage amount (premium mode)")
    parser.add_argument("--type", dest="type_", help="coverage_type (premium mode) or claim_type (eligibility mode)")
    parser.add_argument("--smoker", action="store_true")
    parser.add_argument("--high-risk-occupation", action="store_true")
    parser.add_argument("--family-history", action="store_true")
    parser.add_argument("--manual-labour", action="store_true")
    parser.add_argument("--additional-dependents", action="store_true")

    # eligibility mode
    parser.add_argument("--check-claim", metavar="POLICY_ID", help="policy ID (eligibility mode)")
    parser.add_argument("--amount", type=str, help="claim amount (eligibility mode)")
    parser.add_argument("--claim-date", help="YYYY-MM-DD, defaults to today")
    parser.add_argument("--diagnosis-date", help="YYYY-MM-DD, optional")
    parser.add_argument("--claim-subtype", help="e.g. collision, optional")
    parser.add_argument("--exclusion-code", help="exact exclusion code, optional")
    parser.add_argument("--sub-limit-category", help="key into the policy's sub_limits, optional")
    parser.add_argument("--disability-onset-date", help="YYYY-MM-DD, optional")

    return parser


def _coerce_number(raw):
    # Deliberately not pre-validated beyond "does it look numeric" — an
    # obviously-bad value (e.g. non-numeric age) is passed through as-is
    # so the Lambda's own validation path handles it, rather than the CLI
    # silently swallowing bad input before the tool ever sees it.
    try:
        if "." in raw:
            return float(raw)
        return int(raw)
    except (TypeError, ValueError):
        return raw


def run_premium(args):
    handler = _load_handler("calculate_premium", "calculate_premium.py")

    risk_factors = {}
    for flag, name in [
        (args.smoker, "smoker"),
        (args.high_risk_occupation, "high_risk_occupation"),
        (args.family_history, "family_history"),
        (args.manual_labour, "manual_labour"),
        (args.additional_dependents, "additional_dependents"),
    ]:
        if flag:
            risk_factors[name] = True

    event = {
        "age": _coerce_number(args.age) if args.age is not None else args.age,
        "coverage_amount": _coerce_number(args.coverage) if args.coverage is not None else args.coverage,
        "coverage_type": args.type_,
        "risk_factors": risk_factors,
    }
    result = handler(event, None)

    if result.get("error") is not None:
        print("Error:")
        for field, message in result["error"].items():
            print(f"  - {field}: {message}")
        sys.exit(1)

    print(f"Premium estimate: R{result['premium_estimate']:.2f}/month")
    print(f"Breakdown: {result['breakdown']}")


def run_check_claim(args):
    handler = _load_handler("check_eligibility", "check_eligibility.py")

    claim_date = args.claim_date or date.today().isoformat()

    event = {
        "policy_id": args.check_claim,
        "claim_type": args.type_,
        "claim_amount": _coerce_number(args.amount) if args.amount is not None else args.amount,
        "claim_date": claim_date,
        "diagnosis_date": args.diagnosis_date,
        "claim_subtype": args.claim_subtype,
        "exclusion_code": args.exclusion_code,
        "sub_limit_category": args.sub_limit_category,
        "disability_onset_date": args.disability_onset_date,
    }
    result = handler(event, None)

    if result.get("error") is not None:
        print("Error:")
        for field, message in result["error"].items():
            print(f"  - {field}: {message}")
        sys.exit(1)

    print(f"Eligible: {result['eligible']}")
    print(f"Reason: {result['reason']}")
    if result["approved_amount"] != event["claim_amount"]:
        # "(capped)" only when a sub-limit or coverage-amount cap actually
        # applied — an excess-only reduction isn't a cap, and the reason
        # string above already says "less R<x> excess" or spells out that
        # nothing is payable, so no separate label is needed for that case.
        was_capped = "CAPPED_AT_COVERAGE_AMOUNT_" in result["reason"] or "SUB_LIMIT_APPLIED_" in result["reason"]
        suffix = " (capped)" if was_capped else ""
        print(f"Approved amount: R{result['approved_amount']:,}{suffix}")


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.check_claim:
        run_check_claim(args)
    elif args.age is not None or args.coverage is not None:
        run_premium(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
