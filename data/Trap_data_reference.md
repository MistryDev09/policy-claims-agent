# Trap Data Reference

Deliberate edge cases in `data/policies.json`, `data/claims.json`, and the
policy documents, built to catch naive logic (boolean-only eligibility,
keyword-matching RAG, flat waiting-period assumptions). Use this when
writing `check_claim_eligibility`, `calculate_premium_estimate`, and the
Day 5 eval scenarios.

## ⚠️ Unresolved design inconsistency — decide this before Day 3

**Sub-limit exceeded: denied vs. approved-and-capped.** The dataset
currently models the same situation two different ways and you need to
pick one behavior for your Lambda:

- `CLM-005` (POL-0006, home contents): claim of R500,000 against a
  R350,000 contents sub-limit → **`denied`**, `EXCEEDS_SUB_LIMIT`
- `CLM-011` (POL-0015, portable electronics): claim of R25,000 against a
  R20,000 sub-limit → **`approved`**, capped and paid at R20,000
- `CLM-014` (POL-0020, funeral child benefit): claim of R25,000 against a
  R20,000 sub-limit → **`approved`**, capped and paid at R20,000

Real insurers pay out up to the sub-limit rather than declining outright,
so `approved-and-capped` is the more realistic behavior — but that means
`CLM-005`'s expected status is arguably wrong and should be changed to
`approved` with a capped payout of R350,000. Fix this in the data (or
explicitly document the "deny if it exceeds *any* limit" rule if you'd
rather keep it simple) before you build the eligibility logic around it,
or your eval pass rate will just reflect whichever inconsistent example
you happened to copy the pattern from.

## Same coverage type, functionally different cover (don't assume by type alone)

- **POL-0005 / POL-0013** — both `motor`, comprehensive: collision, fire,
  theft, third-party all covered
- **POL-0010 / POL-0014** — both `motor`, `cover_variant:
  third_party_fire_theft`: collision explicitly **not** covered under any
  circumstance
  - Trap: `CLM-008` and `CLM-009` are both collision claims against
    third-party-only policies → correctly `denied`,
    `EXCLUSION_MATCHED_COLLISION_NOT_COVERED`. If your logic checks
    `coverage_type == "motor"` without checking `cover_variant`, both
    will wrongly pass as covered.

## Same coverage type, opposite waiting-period structure

- **POL-0012** (device): theft has a 14-day wait, accidental damage is
  Day 1
- **POL-0023** (device): accidental damage/screen has a 14-day wait,
  theft is Day 0
  - Trap: a single flat `waiting_period_days` field per policy can't
    represent this correctly for either policy — the real rule is
    per-claim-subtype, not per-policy. Worth deciding whether to model
    this properly (nested waiting periods by claim type) or accept the
    simplification and document it as a known limitation.

## Diagnosis date vs. claim-filed date (critical illness)

- **POL-0018**: policy text is explicit — *"Any illness diagnosed within
  this 90-day window will not be covered, even if the diagnosis is
  confirmed after the waiting period has technically expired."*
  - Trap: `CLM-012` — diagnosis 2024-03-15, policy start 2024-02-01,
    90-day window ends ~2024-05-01. Correct logic must check the
    **diagnosis date** against the waiting period, not the date the claim
    was filed or processed. A Lambda that only compares "today" to
    "start date + waiting period" will approve this incorrectly.

## Two-stage waiting logic (disability)

- **POL-0004**: has both `waiting_period_days: 30` (from policy
  inception) **and** `deferred_period_days: 7` (from the date of
  disability, before payments start) — two different concepts that must
  both be checked, not collapsed into one.
- **POL-0019**: only has `waiting_period_days`, no deferred period at all
  — don't assume every disability policy has both fields.

## Travel: date-bounded vs. duration-based cover

- **POL-0007**: single trip, explicit `start_date` **and** `end_date` —
  cover only exists inside that window
- **POL-0021**: `cover_variant: annual_multi_trip` — no fixed end date,
  covers any trip taken within the 12-month policy period
- **POL-0022**: `cover_variant: single_trip` but (unlike POL-0007) has no
  `end_date` field set — inconsistent with POL-0007's modeling; add an
  `end_date` if you want single-trip logic to be uniform
  - Trap: eligibility logic that assumes every travel policy has a fixed
    end_date will break on POL-0021; logic that ignores end_date entirely
    will wrongly cover claims outside POL-0007's trip window.

## Overlapping exclusions across similar policies (RAG retrieval test)

Policies of the same type with materially different specific exclusions
— good for checking retrieval doesn't just return "the first life policy
it finds":

- **Life**: POL-0001 (self-inflicted 24mo, non-disclosure, criminal act),
  POL-0003 (hazardous hobby w/o rider, act of war, military deployment),
  POL-0011 (non-disclosure, criminal act — no suicide clause, policy is
  old enough it's lapsed), POL-0017 (suicide 24mo, illegal act,
  unlicensed pilot)
- **Critical illness**: POL-0002 (pre-existing cancer, congenital, pro
  contact sport, 180-day wait), POL-0009 (HIV/AIDS no rider,
  self-inflicted, 90-day wait), POL-0018 (pre-existing diabetes, Stage 0
  cancer excluded entirely, 90-day wait with the diagnosis-date trap
  above)

## Out of scope for `calculate_premium_estimate` — should fail gracefully, not silently

`rate_table.json` only covers `life`, `critical_illness`, `disability`,
`funeral`. Policies with these coverage types have no age-band rating and
must not go through the premium calculator:

- `motor` (POL-0005, POL-0010, POL-0013, POL-0014)
- `home` (POL-0006, POL-0015)
- `travel` (POL-0007, POL-0021, POL-0022)
- `device` (POL-0012, POL-0023)
- `pet` (POL-0016)
- `legal` (POL-0024)

Trap: if someone asks the agent "what would my pet insurance premium be
for a 2-year-old dog," the tool must recognize `pet` isn't in
`rate_table.json` and respond accordingly — not silently apply the `life`
or default age-band rates.

## Referential integrity (structural, not a "trap" but check it)

`claims.json` has no foreign-key enforcement — it's flat JSON. Every
`policy_id` in claims currently resolves to a real entry in
`policies.json`, and every `claim_type` matches its policy's
`coverage_type` exactly (verified programmatically when this data was
built). If you hand-add more claims or policies later, re-run that check
— a silent typo here fails quietly instead of throwing an error.