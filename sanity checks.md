Two things to sanity-check before you move on:

- check_claim_eligibility's logic needs to check policy status/exclusion match/waiting period and sub-limits (home, funeral) — don't let the Lambda only check coverage_amount, or CLM-005 will wrongly pass.
- I used waiting_period_days: 2 for the two motor policies (their docs say "48 hours"). If your Lambda does day-based date math this is fine, just don't let it silently round to 0.