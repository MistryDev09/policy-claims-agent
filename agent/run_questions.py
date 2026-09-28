"""
Runs six fixed questions through the agent, one fresh conversation each,
and writes a transcript. This file makes real AWS calls (boto3
bedrock-runtime / bedrock-agent-runtime), it is not run by Claude, only
by the person operating this repo.
"""
import argparse
import os
from datetime import datetime, timezone

import boto3

from tool_loop import REGION, run_turn

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGS_DIR = os.path.join(REPO_ROOT, "logs")

# Each comment is the expected answer to check the transcript against by
# hand — this script does not grade itself.
QUESTIONS = [
    # KB only; expect 30 days, source POL-0006.txt
    "What does the home insurance policy POL-0006 say about the waiting period for theft claims?",
    # premium 487.50
    "I'm 35, a smoker, and want R500,000 of life cover. What would the monthly premium be?",
    # eligible, approved_amount 38,500
    "My car under POL-0005 was in a collision and the repair claim is R45,000. What would I get paid?",
    # eligibility + KB: 30,000 approved, 30-day waiting period
    "Is a R30,000 theft claim on POL-0006 eligible, and what does the policy say about the theft waiting period?",
    # self-correct to child_under_21, approved 20,000
    "I need to claim R25,000 for my child's funeral under POL-0020.",
    # refuse, tool not called
    "How much would pet insurance cost for my 2 year old dog?",
]


def _parse_args():
    parser = argparse.ArgumentParser(description="Run the fixed smoke-test questions through the agent.")
    parser.add_argument(
        "--only",
        type=int,
        metavar="N",
        help="run only question N (1-indexed, matching the order printed and in QUESTIONS) instead of all six",
    )
    return parser.parse_args()


def main():
    args = _parse_args()
    questions = QUESTIONS
    if args.only is not None:
        if not (1 <= args.only <= len(QUESTIONS)):
            raise SystemExit(f"--only must be between 1 and {len(QUESTIONS)}, got {args.only}")
        questions = [QUESTIONS[args.only - 1]]

    os.makedirs(LOGS_DIR, exist_ok=True)
    client = boto3.client("bedrock-runtime", region_name=REGION)
    kb_client = boto3.client("bedrock-agent-runtime", region_name=REGION)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log_path = os.path.join(LOGS_DIR, f"transcript_{timestamp}.md")
    lines = [f"# Transcript {timestamp}\n\n"]

    for question in questions:
        print(f"\nQ: {question}")
        lines.append(f"## Q: {question}\n\n")

        # Fresh conversation per question, as specified — no shared history.
        messages = [{"role": "user", "content": [{"text": question}]}]
        final_text, trace = run_turn(messages, client=client, kb_client=kb_client)

        for t in trace:
            line = f"tool={t['tool']} input={t['input']} status={t['status']}"
            print(f"  [tool] {line}")
            lines.append(f"- {line}\n")

        print(f"A: {final_text}")
        lines.append(f"\n**Answer:** {final_text}\n\n")

    with open(log_path, "w") as f:
        f.writelines(lines)

    print(f"\nWrote {log_path}")
    print("REMINDER: check each answer by hand against the expected value noted in the QUESTIONS comments above.")


if __name__ == "__main__":
    main()
