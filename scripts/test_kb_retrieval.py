"""
Day 2 - test Bedrock Knowledge Base retrieval via RetrieveAndGenerate.

Usage:
    pip install boto3
    export AWS_PROFILE=your-profile   # or set AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY
    python test_kb_retrieval.py --kb-id XXXXXXXXXX --region eu-west-1

Writes results to scripts/day2-retrieval-log.md as you go, so you end up with the
"screenshot or log this working" artifact the brief asks for.
"""

import argparse
import datetime
import os
import boto3


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_LOG_PATH = os.path.join(SCRIPT_DIR, "day2-retrieval-log.md")


QUESTIONS = [
    "What is the waiting period for theft claims under POL-0006?",
    "If a contents claim on POL-0006 comes to R400,000, how much gets paid out?",
    "Is death by accident covered immediately under POL-0008, or is there a waiting period?",
    "How quickly is a funeral claim typically paid out on POL-0008?",
    "Does the suicide exclusion still apply to POL-0011?",
    "What is the waiting period for critical illness cover on POL-0006?",
]


def get_account_id(region: str) -> str:
    sts = boto3.client("sts", region_name=region)
    return sts.get_caller_identity()["Account"]


def run(kb_id: str, region: str, log_path: str):
    client = boto3.client("bedrock-agent-runtime", region_name=region)
    account_id = get_account_id(region)
    model_arn = f"arn:aws:bedrock:{region}:{account_id}:inference-profile/eu.anthropic.claude-haiku-4-5-20251001-v1:0"

    lines = [
        f"# Day 2 retrieval log",
        f"KB ID: `{kb_id}`  ",
        f"Region: `{region}`  ",
        f"Run at: {datetime.datetime.now().isoformat()}",
        "",
    ]

    for i, question in enumerate(QUESTIONS, start=1):
        print(f"\n[{i}/{len(QUESTIONS)}] {question}")
        try:
            response = client.retrieve_and_generate(
                input={"text": question},
                retrieveAndGenerateConfiguration={
                    "type": "KNOWLEDGE_BASE",
                    "knowledgeBaseConfiguration": {
                        "knowledgeBaseId": kb_id,
                        "modelArn": model_arn,
                    },
                },
            )
            answer = response["output"]["text"]
            citations = response.get("citations", [])
            sources = []
            for c in citations:
                for ref in c.get("retrievedReferences", []):
                    uri = ref.get("location", {}).get("s3Location", {}).get("uri", "unknown")
                    sources.append(uri)

            print(f"Answer: {answer}")
            print(f"Sources: {sources}")

            lines.append(f"## Q{i}: {question}")
            lines.append("")
            lines.append(f"**Answer:** {answer}")
            lines.append("")
            lines.append(f"**Sources:** {', '.join(sources) if sources else 'NONE RETURNED'}")
            lines.append("")

        except Exception as e:
            print(f"ERROR: {e}")
            lines.append(f"## Q{i}: {question}")
            lines.append("")
            lines.append(f"**ERROR:** {e}")
            lines.append("")

    with open(log_path, "w") as f:
        f.write("\n".join(lines))

    print(f"\nLog written to {log_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--kb-id", required=True, help="Knowledge Base ID from the console")
    parser.add_argument("--region", default="eu-west-1")
    parser.add_argument("--log", default=DEFAULT_LOG_PATH)
    args = parser.parse_args()

    run(args.kb_id, args.region, args.log)