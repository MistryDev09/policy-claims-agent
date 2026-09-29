**Purpose of this document:** context for any future coding session (Claude Code or otherwise) working on this project. Treat every "Definition of Done" as a hard checkpoint, not a suggestion.

**Why this project exists:** applying to the Sanlam Data, AI and Engineering Academy (closing date 2 October 2026, targeting submission Thursday 1 October, Friday 2 October as buffer). The listing explicitly names AWS, Bedrock, AI AgentCore, Claude, and agentic engineering. A hiring manager tip said to demonstrate AWS skills directly. This project is scoped to prove that, not to be a complete product.

**Working constraint:** 4-5 hours/day, Tue-Sun. Simple beats complex. If a step is fighting you for more than the time budgeted, take the documented fallback and move on. A finished small thing beats an unfinished impressive thing.

---

## What we're building

An agent that answers questions about insurance policies and performs two real calculations, deployed on AWS:

1. **Knowledge base lookup** - answers questions from a set of synthetic policy documents, via Amazon Bedrock Knowledge Bases (managed RAG, not hand-built).
2. **`calculate_premium_estimate`** - a Lambda tool with real deterministic logic (age, coverage amount, risk factors in, premium number out). No LLM arithmetic.
3. **`check_claim_eligibility`** - a Lambda tool with real rule-based logic against a synthetic claims/policy table.

An orchestration loop (Bedrock Converse API, tool use) lets Claude decide which of these to call for a given user question. Deployed via AWS Bedrock AgentCore (Runtime + Gateway) if that goes smoothly, with a documented fallback to plain Lambda + API Gateway if it doesn't.

## Tech stack

- **Bedrock Knowledge Bases** - managed RAG (S3 data source, Titan embeddings, default vector store)
- **AWS Lambda** - the two custom tools
- **Bedrock Converse API** - tool-use / agent loop, model: Claude
- **AgentCore Runtime + Gateway** - deployment layer (stretch goal, see Day 4 fallback)
- **S3** - synthetic policy documents
- **DynamoDB or a simple JSON/CSV in S3** - claims and rate table data (keep this simple, don't stand up RDS for this)
- **CloudWatch billing alarm** - cost guardrail, set on Day 1

## Repo structure (suggested)

```
sanlam-insurance-agent/
  data/
    policies/          # synthetic .txt policy documents
    claims.json         # synthetic claims table
    rate_table.json      # premium calculation inputs
  lambdas/
    calculate_premium/
    check_eligibility/
  agent/
    tool_loop.py        # Bedrock Converse tool-use loop
    tools_schema.json    # tool definitions passed to Claude
  cli_demo.py            # Day 3 small win - direct CLI harness
  eval/
    scenarios.json       # 15-20 test cases
    run_eval.py
  infra/                 # CDK or SAM for deployment
  README.md
```

---

## Day-by-day plan

### Day 1 (Tue): Scope and synthetic data

**Tasks:**

- Write a one-paragraph spec: what the agent does, what it explicitly does not do.
- Generate 10-15 synthetic insurance policy documents (life/short-term style), plain text, varied enough that retrieval has to actually work (different coverage types, exclusions, waiting periods).
- Generate `claims.json` (5-10 synthetic claims: policy ID, claim type, amount, status, reason codes) and `rate_table.json` (age bands, coverage tiers, base rates, risk multipliers).
- Create S3 bucket, IAM roles with least-privilege access.
- Set a CloudWatch billing alarm (e.g. $15 threshold).

**Definition of done:** synthetic data files exist and are internally consistent (a claim references a policy that exists, rate table covers all age/coverage combos you'll test). S3 bucket has policy docs uploaded. Billing alarm is live.

---

### Day 2 (Wed): Managed RAG via Bedrock Knowledge Bases

**Tasks:**

- Create a Bedrock Knowledge Base pointing at the S3 policy documents.
- Use default chunking and Titan embeddings, don't hand-tune this.
- Test retrieval directly via the console and the `RetrieveAndGenerate` API with 5-6 manual questions before writing any surrounding code.

**Definition of done:** you can call `RetrieveAndGenerate` (or `Retrieve`) with a question like "what is the waiting period for critical illness cover on policy X" and get a correct answer sourced from your synthetic docs. Screenshot or log this working.

---

### Day 3 (Thu): The two tools + small win demo

**Tasks:**

- Build `calculate_premium_estimate` as a Lambda function: input (age, coverage amount, coverage type, risk factors), output (premium estimate, breakdown of how it was calculated).
    
- Build `check_claim_eligibility` as a Lambda function: input (policy ID, claim type, claim amount), output (eligible: true/false, reason).
    
- Test both directly with boto3 or local invocation before wiring anything else.
    
- **Small win (build this today, not tomorrow):** a plain CLI script (`cli_demo.py`) with no agent framework involved, that takes a hardcoded or simple input, calls both Lambda functions directly, and prints a clean result. Something like:
    
    ```
    $ python cli_demo.py --age 34 --coverage 500000 --type life
    Premium estimate: R412.50/month
    Breakdown: base rate R380 x risk multiplier 1.08
    
    $ python cli_demo.py --check-claim POL-0042 --type critical_illness --amount 150000
    Eligible: True
    Reason: within coverage limit, waiting period satisfied
    ```
    

**Definition of done:** both Lambda functions return correct results for at least 3 test inputs each. The CLI demo runs end to end and produces real, correct, calculated numbers you did not hardcode. **This is what you show someone today.** It doesn't need the agent or AWS deployment finished to be a legitimate win, it proves the core logic works.

---

### Day 4 (Fri): Agent loop and AgentCore deployment

**Tasks:**

- Write the Bedrock Converse tool-use loop: define tool schemas for both Lambda functions plus the knowledge base retrieval, let Claude decide which to call based on the user's question.
- Test locally with 5-6 varied questions (some needing document lookup, some needing premium calc, some needing eligibility check, at least one needing more than one tool).
- Attempt AgentCore deployment: Runtime for hosting, Gateway to expose the Lambda tools via MCP. **Timebox this to half the day.**
- **Fallback (use if AgentCore is fighting you past the timebox):** deploy the same tool-use loop behind API Gateway + Lambda instead. Still AWS, still a real working agent, document in the README that this was a deliberate scope decision under time constraint, not a failure.

**Definition of done:** the agent correctly routes at least 5 different question types to the right tool(s) and returns correct answers, whether running on AgentCore or the fallback path. Note in the README which path you took and why.

---

### Day 5 (Sat): Eval set, cost guardrails, demo recording

**Tasks:**

- Write 15-20 test scenarios in `eval/scenarios.json` covering: document Q&A, premium calculation, claim eligibility, and at least 2-3 multi-tool questions.
- Run them and record pass rate, fix obvious failures, don't chase 100%, document what fails and why.
- Re-check the billing alarm and actual spend so far.
- Record a 60-90 second screen capture: ask the agent a realistic question, show it reasoning through tool use, show the correct answer.

**Definition of done:** eval results are logged (even a simple pass/fail table in a markdown file counts). Demo video exists and is under 2 minutes.

---

### Day 6 (Sun): README, writeup, submit

**Tasks:**

- Write the README: what it does, architecture diagram (even a simple text/box diagram is fine), AWS services used, how to run it, eval results, honest limitations section (synthetic data, no auth, not production-hardened).
- Add 2-3 lines to your CV or portfolio tying the project directly to Sanlam's listed stack (Bedrock, AgentCore, agentic AI, AI-ready data products).
- Submit the application.

**Definition of done:** repo is public (or shareable), README is something a stranger could read and understand in 2 minutes, application is submitted.

---

## Overall definition of done for the week

- Working agent that correctly uses at least 2 real tools plus a managed knowledge base
- Deployed on AWS (AgentCore or the documented fallback, either is a legitimate result)
- Eval set with logged results
- Demo video
- README that's honest about scope and limitations
- Application submitted Thursday 1 October (Friday 2 October as buffer)

## What we are deliberately not doing

- Hand-building the RAG pipeline (using managed Bedrock Knowledge Bases instead)
- Snowflake or dbt (different skill claim, not enough time to do it credibly)
- A polished frontend (CLI and a short demo video are enough)
- Production-grade auth, rate limiting, multi-tenancy (out of scope for a portfolio piece)