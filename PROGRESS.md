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

## Day 3 (Thu) — The two tools + small win demo — ✅ COMPLETE

**Sub-limit design decision resolved:** approved-and-capped, not denied
outright, for both named sub-limits and overall `coverage_amount`
overruns. Fixed the previously-flagged inconsistency in `claims.json`:
CLM-005 (POL-0006, home contents) now reads `amount: 500000` (numeric),
`status: approved`, `reason_codes: ["SUB_LIMIT_APPLIED_CONTENTS_350000"]`
— consistent with CLM-011 and CLM-014. Referential integrity re-checked
programmatically (every `policy_id` resolves, every `claim_type` matches
its policy's `coverage_type`, all amounts numeric) — clean.

**Lambdas — built, restructured into deployment-shaped subdirectories:**
```
lambdas/
  calculate_premium/
    calculate_premium.py   # fixed from the Day-earlier draft
    rate_table.json        # bundled copy of data/rate_table.json
  check_eligibility/
    check_eligibility.py   # new
    policies.json          # bundled copy of data/policies.json
```
`data/*.json` stay canonical; the `lambdas/*/` copies are the bundled
deployment artifacts (plain copies, not symlinks — re-copy after editing
the canonical files in `data/`). `check_eligibility` does not bundle
`claims.json` — its input is fully structured, nothing in the logic needs
to look up existing claims.

- `calculate_premium_estimate`: fixed the relative-path bug (`BASE_DIR =
  os.path.dirname(os.path.abspath(__file__))` instead of a bare
  `open("rate_table.json")`, which would have broken under Lambda's
  `/var/task` cwd). At the time, the age-parsing bug looked already
  handled correctly in the draft (`int("34.7")` raises `ValueError`, so
  fractional-age *strings* are rejected) — **correction, see the Day 4
  pre-work entry below:** this was only true for strings. A real float
  `34.7` (as opposed to the string `"34.7"`) was silently truncated to
  34 via `int(34.7)` until the Day 4 pre-work fix; that gap is now closed
  for both forms.
- `check_claim_eligibility`: new. Input is structured (not a `claim_id`
  lookup) — `policy_id`, `claim_type`, `claim_amount`, `claim_date`, plus
  four optional fields added to let a structured caller express claim
  specifics that don't exist as granular data on `policies.json`:
  `diagnosis_date` (drives the waiting-period check instead of
  `claim_date` for critical illness), `claim_subtype` (motor collision
  exclusion check), `exclusion_code` (exact match against the policy's
  `exclusion_codes`), `sub_limit_category` (key into `sub_limits`), and
  `disability_onset_date` (paired with `deferred_period_days`). Returns a
  dedicated numeric `approved_amount` field separate from `reason` text.
  **These five fields (plus the four required ones) are the literal tool
  schema Day 4's Bedrock agent should reuse for this tool** — don't
  re-derive the shape from scratch.

**Test results** (13 total, both success and error/edge paths per
function — full input/expected tables in the Day 3 plan file):
- `calculate_premium_estimate`: 5/5 pass — base life premium, smoker
  multiplier applied, invalid `coverage_type` rejected with age-check
  correctly skipped, multi-field error collection (`coverage_type` +
  `coverage_amount` both flagged, `age` not — since `coverage_type` was
  already invalid), funeral age-band boundary with one valid + one
  filtered risk factor.
- `check_claim_eligibility`: 8/8 pass — straightforward approval,
  motor `cover_variant` collision exclusion (CLM-008 trap), diagnosis-date
  vs. claim-date waiting period trap (CLM-012/POL-0018), sub-limit
  capping (CLM-011 and the fixed CLM-005), unknown `policy_id` error path,
  `annual_multi_trip` policy correctly skipping the missing-`end_date`
  check, and a claim correctly denied for falling outside a single-trip
  policy's date window.

**`cli_demo.py`:** built at repo root. Single flat `argparse` parser (no
subcommands) — mode inferred from which flags are present, matching the
brief's two example invocations exactly. Handles both success and error
return shapes cleanly: checks `result["error"] is not None` first, prints
one line per failing field, exits non-zero — no raw dict or traceback
reaches the terminal in either mode. Verified end-to-end for: premium
success, premium validation error, eligibility success with sub-limit
capping (prints an extra `Approved amount: ... (capped)` line), and
eligibility error (`policy_id` not found).

**Judgment calls made beyond what was locked** (confirmed with the user
before implementing):
1. Overall `coverage_amount` exceeded (not a named sub-limit): approved
   and capped at `coverage_amount`, same as the sub-limit rule — the user
   had only explicitly confirmed sub-limits, not this case.
2. The four new optional `check_claim_eligibility` input fields
   (`claim_subtype`, `exclusion_code`, `sub_limit_category`,
   `disability_onset_date`) — needed because `policies.json`/`claims.json`
   don't carry this granularity, and free-text exclusion matching is out
   of scope (that's the Knowledge Base's job, not this Lambda's).

**Known simplifications carried forward as documented limitations** (for
the Day 5 eval set and Day 6 README):
- Per-claim-subtype waiting periods (POL-0012/POL-0023, where theft vs.
  accidental-damage have opposite wait structures) are **not** modeled —
  the Lambda uses the flat `waiting_period_days` field only.
- POL-0022 (`single_trip`, no `end_date` on file) has its date-bounds
  check skipped rather than an invented `end_date` — same treatment as
  the genuinely-dateless `annual_multi_trip` policies, which is a
  simplification, not a fully correct distinction.
- If a policy has `deferred_period_days` but the caller doesn't supply
  `disability_onset_date`, the deferred-period check is skipped (only the
  standard `waiting_period_days` check runs) and the skip is noted in the
  `reason` string rather than silently ignored.
- Retrieval trap from Day 2 (policy ID + common term causing cross-
  document bleed) is unaffected by today's work — `check_claim_eligibility`
  takes `policy_id` as a structured argument, so it's immune to this; the
  limitation is specific to free-text Knowledge Base queries.

**Nothing deviated from the Day 3 prompt's scope** — no AWS deployment, no
boto3, no agent loop attempted; both Lambdas are plain local Python
functions invoked directly by `cli_demo.py`.

---

## Day 3 addendum — pytest suite

Added a real automated test suite in `tests/` (`conftest.py`,
`test_calculate_premium.py`, `test_check_eligibility.py`,
`test_cli_demo.py`) that calls both handlers directly as Python functions
and drives `cli_demo.py` via `subprocess` — no AWS calls, no mocking.
Run with `python3 -m pytest -v` (see `CLAUDE.md`'s Build/test commands).

**Result: 43 passed, 1 skipped, 0 failed.** The one skip is CLM-005's
sibling CLM-007, which is `pending` in `claims.json` — the handler only
ever returns `eligible: True/False`, so there's nothing to assert a
pending claim against; skipped with a reason rather than silently
dropped. No test was weakened to match the code's output — expected
premiums were computed by hand from `rate_table.json`, and no handler
code, data file, or `cli_demo.py` was touched to make a test pass.

**Notable finding — no bugs surfaced, but replay required test-side
inference:** the eligibility replay test parametrizes over all 14 claims
in `claims.json` and re-derives the expected `eligible`/`approved_amount`
from each claim's real outcome. `claims.json` only stores human-readable
`reason_codes` (e.g. `"SUB_LIMIT_APPLIED_CONTENTS_350000"`,
`"EXCLUSION_MATCHED_COLLISION_NOT_COVERED"`), not the handler's
structured optional fields (`sub_limit_category`, `exclusion_code`) — so
the test derives those fields from the reason code text purely as a
test-harness convenience for replay. With that derivation, **all 13
non-pending claims replay correctly against the handler**, including the
ones the task brief expected might need `xfail` (CLM-006, CLM-008,
CLM-009, CLM-010 — all exclusion-based denials): the handler's generic
`exclusion_code` field is sufficient to reproduce them once the exact
code is supplied, so none needed `xfail`.

**Correction (this was overstated when first written):** for the four
exclusion-based denials, this is *not* independent validation that
`check_claim_eligibility` agrees with the recorded outcome — the test
derives `exclusion_code` from the very `reason_codes` string that states
the outcome, then feeds it back in. All it proves is that *given* the
correct exclusion code, the handler correctly denies and reports
`approved_amount: 0` — the handler never independently decides whether
`COLLISION_NOT_COVERED` *should* apply to a given claim; the caller
(test, or later the Day 4 agent) asserts that. `exclusion_code` is
caller-asserted by design (see the Day 4 pre-work README-limitations
stub below) — the one exception is the motor/`third_party_fire_theft`
+ `claim_subtype` path, which *is* the handler's own domain logic and
is independently exercised (CLM-008/009 now also require `claim_subtype`
directly, not just `exclusion_code`, per the Day 4 pre-work fix).

**Assumptions made about the handler's event shape** (documented in the
test file itself, repeated here for visibility):
- `claim_date` is **required**, not optional — the task brief assumed it
  might be optional; `cli_demo.py` defaults it to today's date when the
  flag is omitted, but the handler itself errors without it.
- There is no `claim_category` field (the brief's guess); the real field
  is `sub_limit_category`, a key into the policy's `sub_limits` dict.
- Deriving `exclusion_code`/`sub_limit_category` from `claims.json`'s
  `reason_codes` for the replay test is a test-only convenience — the
  real Day 4 agent will supply these fields directly from its own claim
  intake, not by parsing a reason-code string.

**Nothing left open as a bug from this pass** — no failing test is being
carried forward; the single skip (CLM-007, pending) is a scope boundary
of the handler, not a defect.

---

## Day 3 addendum — mutation testing + 3 real fixes found by review

Ran a manual mutation-testing pass: deliberately broke `check_eligibility`
and `calculate_premium` one bug at a time, confirmed the suite caught it,
then reverted with `git checkout`. Results:

| Mutation | Caught? |
|---|---|
| waiting-period `<` → `<=` | ✅ yes (`test_waiting_period_boundary`) |
| life age 31-45 rate 0.65 → 0.66 | ✅ yes (7 tests failed) |
| deleted the sub-limit cap (`approved_amount = sub_limit`) | ✅ yes (3 replay tests failed: CLM-005/011/014) |
| dropped the `is True` check on risk factors (`risk_factors.get(name)` truthy-only) | ❌ **not caught initially** |

The 4th mutation exposed a real gap: the existing `{"high_risk_occupation":
False}` test only proves `False` doesn't apply, and `False` is falsy
under any truthy check — it can't distinguish `is True` from a plain
truthiness check. Added `{"smoker": 1}` (truthy-but-not-`True`) as a new
success case in `test_calculate_premium.py`, confirmed it passes clean and
fails against the reintroduced mutation, then reverted the mutation.

**Three separate review findings, fixed in `check_eligibility.py`:**
1. **Unrecognized `sub_limit_category`** returned an error but the message
   didn't list the policy's actual valid keys — an agent guessing wrong
   had nothing to correct against. Fixed: message now includes
   `(valid: [...])`.
2. **Unrecognized `exclusion_code`** wasn't an error at all — it silently
   no-op'd and fell through to the coverage/sub-limit check as if nothing
   had been supplied, giving a caller zero feedback on a typo'd code.
   Fixed: now a validation error, same "(valid: [...])" pattern as above.
3. **`excess` (POL-0005: 6500, POL-0012: 750) was completely unused** —
   present in `policies.json` but never read anywhere in the handler, so
   `approved_amount` never reflected it. Fixed: deducted from
   `approved_amount` last (after any sub-limit/coverage-amount capping),
   floored at 0, noted in the `reason` string. This changes CLM-004's
   expected replay outcome (POL-0005, motor) from `approved_amount:
   45000` to `38500` — `claims.json`'s `"amount"` field was always the
   claimed amount, not a stated payout, so this isn't a data
   inconsistency the way CLM-005 was; the replay test now accounts for
   `excess` generically for any policy that carries one.

Added 4 new tests covering all three fixes (`test_excess_deducted_from_
approved_amount`, `test_excess_floors_at_zero_not_negative`,
`test_unknown_sub_limit_category_lists_valid_values`,
`test_unknown_exclusion_code_errors_and_lists_valid_values`) plus the
`{"smoker": 1}` case above. Full suite: **48 passed, 1 skipped** (still
just CLM-007).

**Still not modelled, left as a known limitation:** per-claim-subtype
waiting periods, POL-0022's missing `end_date`, and deferred-period skip
behavior (see the earlier Day 3 entry) — none of today's fixes touch
those.

---

## Day 4 pre-work: input validation, fail-closed optional fields, excess reason

Ran a TDD pass on both handlers ahead of the Day 4 agent-loop work:
wrote failing tests reproducing 8 real gaps (see below), fixed the
handlers, fixed the tests those fixes broke, then re-ran boundary
mutation tests on `calculate_premium` to confirm the existing suite
still catches off-by-one errors. Full suite: **59 passed, 1 skipped, 0
failed** (up from 48+1 — 11 new tests, 5 changed).

**Fixes:**
1. `calculate_premium`: a real float age (`34.7`, as opposed to the
   already-rejected string `"34.7"`) was silently truncated to 34 via
   `int(34.7)`. Now rejected the same as the string form; an
   integer-valued float (`34.0`) is still accepted.
2. `calculate_premium`: `coverage_amount=True` passed validation (bool is
   an `int` subclass in Python, so `isinstance(True, (int, float))` is
   `True` and `True == 1`). Now explicitly rejected.
3. `calculate_premium`: `coverage_amount` now must have at most 2 decimal
   places (`round(x, 2) == x`) — it's a currency amount. `1000.505`
   rejected, `1000.50` still accepted.
4. `calculate_premium`: `risk_factors` must be a `dict`, else a clean
   error instead of an `AttributeError` crash (a list or string blew up
   `risk_factors.get(name)`). A recognized key (valid multiplier for the
   given `coverage_type`) with a non-bool value (e.g. `"yes"`, `1`) is
   now an error naming the field, not silently filtered — unknown keys
   are still silently filtered as before.
5. `check_claim_eligibility`: `diagnosis_date` is now **required**
   (validation error, not optional) when the resolved policy's
   `coverage_type` is `critical_illness` — previously a missing
   `diagnosis_date` silently fell back to `claim_date`, which is exactly
   the failure mode the diagnosis-date trap (POL-0018/CLM-012) exists to
   catch. Error text tells the caller to go ask the user for it.
6. `check_claim_eligibility`: `claim_subtype` is now **required** when
   the resolved policy is `motor` with `cover_variant:
   third_party_fire_theft` — previously a missing `claim_subtype`
   silently approved everything, including collision claims that should
   be denied. Error text lists example values (`collision`, `fire`,
   `theft`).
7. `check_claim_eligibility`: when a policy's `excess` fully absorbs the
   payout (`approved_amount` floors at 0), `reason` now says so plainly
   (`"claim amount does not exceed the R<excess> excess — nothing
   payable"`) instead of appending "less R<x> excess" to a "within
   coverage limit" sentence that's no longer true once nothing is
   payable.
8. `cli_demo.py`: the `(capped)` label on `Approved amount:` now only
   prints when a sub-limit or coverage-amount cap actually applied
   (checked via the `SUB_LIMIT_APPLIED_`/`CAPPED_AT_COVERAGE_AMOUNT_`
   markers in `reason`) — previously it printed whenever
   `approved_amount != claim_amount` for *any* reason, including a pure
   excess deduction, which isn't a cap.

**Tests changed (not just added), and why:**
- `test_calculate_premium.py`: moved `("life", 34, 500000, {"smoker": 1},
  325.0)` out of the success cases and into the error cases (expecting
  `error["risk_factors"]`) — fix #4 above deliberately supersedes the
  old "truthy-but-not-True is silently filtered" rule for a *recognized*
  key; this is a sanctioned behavior change, not a loosened assertion.
- `test_check_eligibility.py`: the replay test for CLM-002, CLM-008,
  CLM-009, and CLM-012 now supplies `diagnosis_date`/`claim_subtype`
  values taken from `Trap_data_reference.md` (CLM-012's diagnosis date
  `2024-03-15` and CLM-008/009's `claim_subtype: "collision"` are
  documented there; CLM-002 has no distinct diagnosis date recorded
  anywhere, so it uses `date_filed` as the most defensible real value —
  the claim is still denied either way, well inside the 180-day waiting
  period). Fixes #5 and #6 above made these claims newly fail validation
  without those fields.
- `test_check_eligibility.py`: strengthened (not loosened)
  `test_excess_floors_at_zero_not_negative` to also assert the new
  explicit reason text, and added
  `test_excess_exactly_equal_to_claim_amount_floors_at_zero` for the
  boundary case (`claim_amount == excess`).

**Boundary mutation tests on `calculate_premium`** (run, confirmed
failure, reverted via `git checkout`):
- age-band lookup `<= max_age` → `< max_age`: caught by the existing
  `life age 75` boundary case (no new test needed).
- `coverage_amount <= 10_000_000` → `< 10_000_000`: caught by the
  existing `coverage_amount = 10_000_000` boundary case (no new test
  needed).

**README-limitations stub** (for Day 6, carried forward from this
session's findings — order these under a "Known limitations" heading):
- Order of operations in `check_claim_eligibility`: sub-limit cap is
  checked first; if none applies, the overall `coverage_amount` cap is
  checked; `excess` (if the policy has one) is deducted last, floored at
  0, from whichever of those produced the pre-excess approved amount.
- Claims exceeding the overall `coverage_amount` (not a named sub-limit)
  are approved-and-capped, same as sub-limits — not denied outright.
- `excess` is only modelled for policies that carry the field
  (`POL-0005`, `POL-0012` in this dataset) and is a flat deduction, not
  a percentage or a per-claim-type variant.
- `risk_factors` validation: a key valid for the given `coverage_type`
  must be a real `bool`; unknown keys are silently filtered; the whole
  input must be a `dict`.
- `exclusion_code` is **caller-asserted** — the handler doesn't decide
  whether an exclusion applies to a claim's facts, it just checks
  whether the code the caller supplied is a real code on this policy and
  denies if so. The Day 4 agent (or a human) is responsible for deciding
  which exclusion, if any, applies before calling this tool with it.
- Per-claim-subtype waiting periods (POL-0012/POL-0023, theft vs.
  accidental-damage having opposite wait structures) are not modelled —
  a single flat `waiting_period_days` is used regardless of subtype.
- POL-0022 (`single_trip`, no `end_date` on file) has its travel
  date-bounds check skipped, the same as the genuinely-dateless
  `annual_multi_trip` policies — a simplification, not a fully correct
  distinction between the two `cover_variant`s.

---

## Day 4-6

Not started. See original brief for task breakdown. Day 4 should reuse
`check_claim_eligibility`'s finalized field list (above) as the literal
Bedrock tool schema rather than re-deriving it.
