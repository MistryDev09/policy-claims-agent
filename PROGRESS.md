# Progress Log

Companion to `Project Brief - Insurance Policy & Claims Agent`. Update this
after each day so any future session (Claude Code or otherwise) has real
state to work from instead of re-deriving it.

---

## Day 1 (Tue) — Scope and synthetic data — ✅ COMPLETE

**Spec:** written (not reproduced here — see repo).

**Region decision:** `eu-west-1` (Europe, Ireland) for everything —
Bedrock, Knowledge Bases, S3, Lambda. Chose this over `af-south-1` (Cape
Town) because Bedrock Knowledge Bases is not yet on AWS's supported
region list for af-south-1, even though model invocation is. Keep
everything in eu-west-1 all week; do not mix regions.

**Synthetic data — done, validated:**
- `data/policies/POL-0001.txt` through `POL-0024.txt` — 24 policy
  documents. Types: life, critical_illness, disability, motor
  (comprehensive + third-party/fire/theft variants), home, travel (single
  + annual multi-trip variants), funeral, device, pet, legal.
- `data/policies.json` — 24 entries, structured fields matching the docs
  (coverage_type, coverage_amount, waiting_period_days, exclusion_codes,
  sub_limits where relevant, cover_variant for motor/travel splits).
- `data/claims.json` — CLM-001 through CLM-014. Every `policy_id`
  resolves to a real policy; every `claim_type` matches its policy's
  `coverage_type` (checked programmatically).
- `data/rate_table.json` — age-band rates for the 4 underwritten types
  only (life, critical_illness, disability, funeral). Motor/home/travel/
  device/pet/legal are deliberately excluded from premium calc — they're
  asset-rated in reality, not age-rated. `calculate_premium_estimate`
  must reject/handle these gracefully, not silently misapply life rates.
- `trap-data-reference.md` — catalog of deliberate edge cases for eval
  design (sub-limit exceeded, waiting-period-by-subtype, diagnosis-date
  vs claim-filed-date, motor cover_variant traps, etc). Read this before
  writing `check_claim_eligibility`.

**⚠️ Open decision, deferred on purpose:** sub-limit-exceeded claims are
currently modeled two ways in the data — CLM-005 is `denied`, CLM-011 and
CLM-014 are `approved` and capped at the sub-limit. Pick one behavior
before building the eligibility Lambda on Day 3. Real insurers pay up to
the sub-limit rather than declining outright, so `approved-and-capped` is
the more realistic default — but this is a decision to make explicitly,
not inherit by accident. Full detail in `trap-data-reference.md`.

**AWS infrastructure — done:**
- S3 bucket: `sanlam-insurance-agent-devakmistry-2026` (eu-west-1), all
  24 policy docs uploaded.
- IAM role: `sanlam-agent-bedrock-kb-role` — trust policy scoped to
  `bedrock.amazonaws.com`, inline permissions policy scoped to
  `s3:GetObject`/`s3:ListBucket` on the one bucket plus
  `bedrock:InvokeModel` on `amazon.titan-embed-text-v1` only. Role ARN:
  *(paste in once copied — see IAM console → role summary)*.
- CloudWatch billing alarm: `sanlam-agent-billing-15usd`, threshold
  $15, in `us-east-1` (billing metrics are account-wide and only live in
  us-east-1 regardless of build region). SNS email subscription —
  *(confirm this was actually clicked in the confirmation email; not
  verified as of end of Day 1)*.
- Bedrock model access: Titan Embeddings activates automatically on
  first Knowledge Base sync (Day 2), nothing to do in advance. Claude
  model access required a one-time use-case form (company name + URL) —
  *(confirm this cleared before starting Day 2; was pending when Day 1
  ended)*.

**Not started (correctly, per plan):** Knowledge Base creation,
retrieval testing, Lambda functions, agent loop, AgentCore deployment.

---

## Day 2 (Wed) — Managed RAG via Bedrock Knowledge Bases — ✅ COMPLETE

**Knowledge Base — created:**
- Bedrock Knowledge Base `sanlam-policy-kb`, KB ID `3VPWHXL63S`, region
  `eu-west-1`.
- Embeddings: Titan Text Embeddings V2, 1024 dims, floating-point,
  default chunking (~300 tokens).
- Vector store: Amazon S3 Vectors, quick-create (not OpenSearch
  Serverless — see `CONTEXT.md` for the cost rationale).
- Data source scoped to
  `s3://sanlam-insurance-agent-devakmistry-2026/policies/` — excludes
  `claims.json` / `rate_table.json`.
- Service role auto-created by the console:
  `AmazonBedrockExecutionRoleForKnowledgeBase_m5j4u` (the console did not
  offer the pre-made `sanlam-agent-bedrock-kb-role` for the S3 Vectors
  path).

**IAM — root user blocked:**
- AWS root user cannot create Bedrock Knowledge Bases (platform
  restriction). Created IAM user `devakmistry-admin` (`AdministratorAccess`)
  for this and all subsequent AWS work. Rationale documented in
  `CONTEXT.md`.

**Sync:**
- Synced 24/24 documents successfully.
- Sync is a manual step separate from KB creation — the first
  `RetrieveAndGenerate` test returned 0 source chunks because the sync
  hadn't been triggered yet.

**Retrieval testing:**
- Tested `RetrieveAndGenerate` with 6 manual questions against real
  content from POL-0006, POL-0008, POL-0011: **5/6 correct and properly
  sourced**, 1 reproducible failure (logged in `Trap_data_reference.md` —
  policy ID + common term causes cross-document bleed).

**Day 2 Definition of Done met:** correct, sourced answers from the
synthetic docs, logged via the console test panel and a boto3 script.

---

## Day 3-6

Not started. See original brief for task breakdown.
