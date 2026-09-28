import json
import os
from datetime import date, timedelta

# Loaded once at module level (warm-container reuse), resolved relative to
# this file's own location — not the process cwd — so it still works once
# packaged into a Lambda deployment zip (cwd there is /var/task).
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(BASE_DIR, "policies.json")) as f:
    POLICIES_BY_ID = {p["policy_id"]: p for p in json.load(f)}

DATE_FIELDS = ["claim_date", "diagnosis_date", "disability_onset_date"]


def _parse_date(value):
    return date.fromisoformat(value)


def lambda_handler(event, context):
    """
    Input event:
        policy_id: str, required, must exist in policies.json
        claim_type: str, required. Compared against the policy's real
            coverage_type. A mismatch is a validation error, not a
            denial, since claim_type is a guess the caller has to make
            from a policy_id alone; the error names the policy's actual
            coverage_type so the caller can retry with the correct
            value instead of hitting a dead end.
        claim_amount: number, required, > 0
        claim_date: str "YYYY-MM-DD", required
        diagnosis_date: str "YYYY-MM-DD". REQUIRED when the resolved
            policy's coverage_type is critical_illness (otherwise
            optional/unused), drives the waiting-period check instead of
            claim_date (a policy can exclude an illness diagnosed inside
            the waiting period even if the claim itself is filed later).
            Missing it on a critical_illness claim is a validation error,
            not a silent fall-back to claim_date. critical_illness is
            hard-coded as the one coverage_type where diagnosis_date
            matters, a deliberate, narrow rule (this dataset has no
            other coverage_type where a diagnosis date is meaningful),
            not a general "always ask for a diagnosis date" policy.
        claim_subtype: str, e.g. "collision". REQUIRED when the resolved
            policy's coverage_type is motor and cover_variant is
            third_party_fire_theft (otherwise optional/unused), since
            without it there's no way to tell a covered peril (fire,
            theft) from an excluded one (collision). Missing it in that
            case is a validation error, not a silent approval.
        exclusion_code: str, optional, exact code checked against the
            policy's exclusion_codes list.
        sub_limit_category: str, optional, key into the policy's
            sub_limits dict.
        disability_onset_date: str "YYYY-MM-DD", optional, used together
            with the policy's deferred_period_days.

    Success return:
        {"eligible": bool, "approved_amount": number, "reason": str,
         "error": None}

    Error return (any validation failure):
        all 9 input fields echoed back, plus
        {"error": {"<field>": "<description>", ...}}
        eligible/approved_amount/reason are absent entirely, not
        present-and-null. An unrecognized sub_limit_category or
        exclusion_code is a validation error (not a silent no-op), and
        the message lists the policy's actual valid values so a caller
        can self-correct. A missing diagnosis_date/claim_subtype where
        the policy requires one (see above), or a claim_type that does
        not match the policy's real coverage_type, is also a validation
        error, with message text aimed at telling the caller what to go
        ask the user for or what to retry with: every error message in
        this handler is written to be relayed by an agent to a human,
        not just logged for a developer.

    Denial checks run in order and short-circuit at the first one that
    fires. Capping (sub-limit, else overall coverage_amount) only happens
    once every denial-type check has passed clean. If the policy carries
    an `excess` (POL-0005, POL-0012 in this dataset), it's deducted from
    the approved amount last, floored at 0. If the excess alone wipes out
    the payout, `reason` says so explicitly instead of implying a normal
    within-limit approval. That message is inserted at the front of
    `reason`'s notes, not a replacement for them: any earlier note
    (a SUB_LIMIT_APPLIED/CAPPED_AT_COVERAGE_AMOUNT cap, a deferred-period
    or missing-travel-end_date caveat) survives alongside it.
    """
    policy_id = event.get("policy_id")
    claim_type = event.get("claim_type")
    claim_amount = event.get("claim_amount")
    claim_date_raw = event.get("claim_date")
    diagnosis_date_raw = event.get("diagnosis_date")
    claim_subtype = event.get("claim_subtype")
    exclusion_code = event.get("exclusion_code")
    sub_limit_category = event.get("sub_limit_category")
    disability_onset_date_raw = event.get("disability_onset_date")

    raw_by_field = {
        "claim_date": claim_date_raw,
        "diagnosis_date": diagnosis_date_raw,
        "disability_onset_date": disability_onset_date_raw,
    }

    def echo():
        return {
            "policy_id": policy_id,
            "claim_type": claim_type,
            "claim_amount": claim_amount,
            "claim_date": claim_date_raw,
            "diagnosis_date": diagnosis_date_raw,
            "claim_subtype": claim_subtype,
            "exclusion_code": exclusion_code,
            "sub_limit_category": sub_limit_category,
            "disability_onset_date": disability_onset_date_raw,
        }

    errors = {}

    # independent checks — always run regardless of each other
    policy = POLICIES_BY_ID.get(policy_id)
    if policy is None:
        errors["policy_id"] = "not found"

    if not isinstance(claim_amount, (int, float)) or isinstance(claim_amount, bool) or claim_amount <= 0:
        errors["claim_amount"] = "must be a positive number"

    parsed_dates = {}
    for field in DATE_FIELDS:
        raw = raw_by_field[field]
        if raw is None:
            continue
        try:
            parsed_dates[field] = _parse_date(raw)
        except (TypeError, ValueError):
            errors[field] = "must be YYYY-MM-DD"

    if claim_date_raw is None:
        errors["claim_date"] = "required"

    # sub_limit_category / exclusion_code validity depends on having found
    # the policy — only checked once policy_id resolved. Both list the
    # policy's actual valid values so a caller (the Day 4 agent) has
    # something to correct itself against, instead of a bare "invalid".
    if policy is not None and sub_limit_category is not None:
        valid_categories = sorted(policy.get("sub_limits", {}))
        if sub_limit_category not in valid_categories:
            errors["sub_limit_category"] = (
                f"not a valid sub-limit for this policy (valid: {valid_categories})"
            )

    if policy is not None and exclusion_code is not None:
        valid_codes = sorted(policy.get("exclusion_codes", []))
        if exclusion_code not in valid_codes:
            errors["exclusion_code"] = (
                f"not a valid exclusion code for this policy (valid: {valid_codes})"
            )

    # diagnosis_date is required (not just optional) for critical_illness —
    # without it, the waiting-period check falls back to claim_date, which
    # is exactly the trap this field exists to catch (a diagnosis made
    # inside the waiting period is excluded even if the claim is filed
    # later). Fail closed instead of silently using the wrong date.
    if policy is not None and policy.get("coverage_type") == "critical_illness" and diagnosis_date_raw is None:
        errors["diagnosis_date"] = (
            "required for critical_illness claims — ask the user when the condition was diagnosed"
        )

    # claim_subtype is required (not just optional) for third_party_fire_
    # theft motor policies — without it there's no way to tell a covered
    # peril (fire, theft) from an excluded one (collision), and today the
    # claim would silently be approved either way.
    if (
        policy is not None
        and policy.get("coverage_type") == "motor"
        and policy.get("cover_variant") == "third_party_fire_theft"
        and claim_subtype is None
    ):
        errors["claim_subtype"] = (
            "required for third-party/fire/theft motor claims, ask the user which peril applies "
            "(e.g. 'collision', 'fire', 'theft')"
        )

    # claim_type not matching the policy's real coverage_type is a
    # validation error, not a denial. The caller only ever knows the
    # policy_id from the user, so it has to guess claim_type; a wrong
    # guess is bad input, not a real denied claim, and the message names
    # the correct type so the caller can retry automatically instead of
    # hitting a dead end.
    if policy is not None and claim_type != policy.get("coverage_type"):
        errors["claim_type"] = (
            f"policy {policy_id} is a {policy['coverage_type']} policy, not {claim_type}; "
            f"retry with claim_type '{policy['coverage_type']}'"
        )

    if errors:
        return {**echo(), "error": errors}

    # --- past this point: policy exists, claim_amount is valid, all
    # supplied dates parse, sub_limit_category (if given) is valid ---

    claim_date = parsed_dates["claim_date"]
    diagnosis_date = parsed_dates.get("diagnosis_date")
    disability_onset_date = parsed_dates.get("disability_onset_date")

    def deny(reason):
        return {**echo(), "eligible": False, "approved_amount": 0, "reason": reason, "error": None}

    if policy.get("status") != "active":
        return deny(f"policy is not active (status: {policy.get('status')})")

    if (
        policy.get("coverage_type") == "motor"
        and policy.get("cover_variant") == "third_party_fire_theft"
        and claim_subtype == "collision"
    ):
        return deny("EXCLUSION_MATCHED_COLLISION_NOT_COVERED")

    # waiting period — diagnosis_date drives this for critical_illness
    # when supplied, per the "diagnosed within the window is excluded even
    # if the claim is filed later" trap; otherwise claim_date applies.
    if policy.get("coverage_type") == "critical_illness" and diagnosis_date is not None:
        effective_date = diagnosis_date
    else:
        effective_date = claim_date

    waiting_period_days = policy.get("waiting_period_days", 0)
    start_date = _parse_date(policy["start_date"])
    if effective_date < start_date + timedelta(days=waiting_period_days):
        return deny("WAITING_PERIOD_NOT_MET")

    reason_notes = []

    # deferred period (disability two-stage waiting) — only evaluated if
    # an onset date was supplied; otherwise skipped and annotated rather
    # than silently ignored.
    deferred_period_days = policy.get("deferred_period_days")
    if deferred_period_days is not None:
        if disability_onset_date is not None:
            if claim_date < disability_onset_date + timedelta(days=deferred_period_days):
                return deny("DEFERRED_PERIOD_NOT_MET")
        else:
            reason_notes.append("deferred period not evaluated — no onset date supplied")

    # travel date bounds — only evaluated when the policy has an end_date
    # on file (annual_multi_trip policies, and some single_trip records in
    # this dataset, don't carry one).
    if policy.get("coverage_type") == "travel":
        end_date_raw = policy.get("end_date")
        if end_date_raw is not None:
            end_date = _parse_date(end_date_raw)
            if not (start_date <= claim_date <= end_date):
                return deny("TRAVEL_DATE_OUTSIDE_POLICY_WINDOW")
        else:
            reason_notes.append("trip end date not on file — date bounds not evaluated")

    # exclusion_code validity (against this policy's actual exclusion_codes)
    # was already enforced above, in the validation pass — by this point,
    # if it was supplied at all, it's a real match.
    if exclusion_code is not None:
        return deny(f"EXCLUSION_MATCHED_{exclusion_code}")

    # sub-limit cap
    sub_limit_applied = False
    if sub_limit_category is not None:
        sub_limit = policy["sub_limits"][sub_limit_category]
        if claim_amount > sub_limit:
            reason_notes.insert(0, f"SUB_LIMIT_APPLIED_{sub_limit_category.upper()}_{sub_limit}")
            approved_amount = sub_limit
            sub_limit_applied = True

    # overall coverage_amount cap — only when no named sub-limit already
    # capped this claim (a sub-limit is always <= coverage_amount in this
    # dataset, so there's nothing further to cap once one has applied).
    if not sub_limit_applied:
        coverage_amount = policy["coverage_amount"]
        if claim_amount > coverage_amount:
            reason_notes.insert(0, f"CAPPED_AT_COVERAGE_AMOUNT_{coverage_amount}")
            approved_amount = coverage_amount
        else:
            reason_notes.insert(0, "within coverage limit, waiting period satisfied, no exclusion matched")
            approved_amount = claim_amount

    # policy excess: a fixed amount the policyholder carries themselves on
    # any approved payout (motor/device policies in this dataset). Applied
    # last, after any sub-limit/coverage-amount capping, and floored at 0.
    # When the excess wipes out the payout entirely, say so plainly rather
    # than appending "less R<x> excess" to a "within coverage limit"
    # sentence that's no longer true once nothing is actually payable.
    excess = policy.get("excess")
    if excess:
        pre_excess_amount = approved_amount
        approved_amount = max(0, pre_excess_amount - excess)
        # approved_amount == 0 is implied by pre_excess_amount <= excess
        # (max(0, non-positive) == 0), so checking the latter alone is
        # equivalent and doesn't repeat the same fact twice.
        if pre_excess_amount <= excess:
            # Insert, don't overwrite: whatever's already in reason_notes
            # (a SUB_LIMIT_APPLIED/CAPPED_AT_COVERAGE_AMOUNT note, a
            # deferred-period or missing-end_date caveat) is still true
            # and still relevant — the excess wiping out the payout is an
            # additional fact, not a replacement for the others.
            reason_notes.insert(0, f"claim amount does not exceed the R{excess} excess — nothing payable")
        else:
            reason_notes.append(f"less R{excess} excess")

    return {
        **echo(),
        "eligible": True,
        "approved_amount": approved_amount,
        "reason": ", ".join(reason_notes),
        "error": None,
    }
