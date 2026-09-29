# Eval Findings

Full account of the Day 5 eval runs against the deployed AgentCore Gateway,
moved here from `PROGRESS.md`. The scenarios themselves live in
`eval/scenarios.json`, and raw per-run reports in `eval/results/`.

Full honesty about the whole process, not just the final number, since
that is the only way this section is useful to anyone reading it later.

## Run history

**Before fixing scenarios 3/8/14, two full gateway runs
(20260928T222735Z and 20260929T060733Z) both showed the same result:**
20/23 on the strict scenarios, 3 failures, all three read from the
actual transcript rather than trusted from the pass/fail line alone:
- Scenarios 8 and 14 required the agent to guess `claim_type`
  (`motor`) wrong before self-correcting to the right one (`home`). The real
  transcript showed the agent inferring the correct type on the first
  attempt in both cases, helped by contextual words like "burglary,"
  a better outcome than the assertion allowed for, not a failure.
  Fixed by asserting only the correct final state, since scenario 9
  already exercises the self-correction mechanism directly.
- Scenario 3 was phrased as a premium/cost question ("how much would
  X cost me") but asserted a `search_policy_documents` call; the
  agent correctly routed it through the premium-refusal path instead,
  which the assertion did not allow for. Fixed by rewording the
  question to an unambiguous document question with nothing in the KB
  to answer it.

**After that fix, three further full gateway runs, reported exactly as
they came out rather than rounded to "it's fixed now":**
- 20260929T124954Z: 23/23.
- 20260929T130113Z: 22/23. The one failure was scenario 3 again, but a
  different and unrelated cause: the agent asked for a policy ID
  before searching, since the reworded question (deliberately) does
  not name one, so `search_policy_documents` was never called on that
  particular run. This is a real, minor flakiness in how scenario 3 is
  phrased, not yet fixed, and is being recorded honestly rather than
  treated as the earlier design bug resurfacing.
- 20260929T130818Z: 23/23.

**Summary of the run history:** the first gateway run scored 20/23 (87%),
and a second run before any fix scored the same. All three failures
(scenarios 3, 8, 14) were scenario-design bugs found by the runs, not
agent bugs; each was loosened or reworded to assert the correct outcome
rather than a specific path. This is exactly the kind of finding a good
eval process is supposed to surface. Three later runs scored 23/23,
22/23 (scenario 3 phrasing flakiness, still open), and 23/23.

## The incident-date finding (scenario 13)

**Scenario 13 (`limitation`, `strict: false`, intentionally never
pass/failed) was run twice and showed two different behaviors, which
is itself the most useful finding of the eval, not a coincidence to
gloss over:**
- 20260929T124954Z: the agent passed today's date as `claim_date`
  instead of the stated incident date (2026-06-06), so the tool
  technically and correctly returned `eligible: true` against the
  input it was actually given. The agent then noticed the mismatch by
  cross-referencing the retrieved POL-0012 policy text, manually
  computed the real 5-day gap against the 14-day waiting period, and
  overrode the tool's answer in its final response, correctly telling
  the user the claim is not eligible.
- 20260929T130818Z: the agent correctly passed the stated incident
  date (2026-06-06) as `claim_date`, and the tool itself returned
  `eligible: false`, `WAITING_PERIOD_NOT_MET`, directly, no override
  needed.

Both final answers were correct, but by two different and not equally
reliable paths. This reveals a real schema gap, not a flaky model
quirk: `check_claim_eligibility` has no field distinguishing "date of
the incident" from "date the claim is filed" (`claim_date` is used for
both), so whether waiting-period math is evaluated against the right
date depends on whether the agent happens to map the user's stated
incident date onto `claim_date`. When it does not, the agent has been
observed to catch and self-correct the resulting technically-valid-
but-substantively-wrong tool answer, but nothing guarantees that
correction happens on every run.

An eval scenario built to test one documented limitation (the flat,
per-policy `waiting_period_days` field cannot represent per-claim-
subtype rules) surfaced a more important, previously unnoticed one
instead (no incident-date field). That is the eval process working as
intended, not a coincidence.

The fix (an `incident_date` field on `check_claim_eligibility`, separate
from `claim_date`) is listed under Future work in `README.md`. It is not
implemented, since it needs both a schema change and a full retest cycle.
