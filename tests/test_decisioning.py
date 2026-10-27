"""
Unit tests for the decisioning layer: reason codes, sensitivity, policy rules, cut-off
tuning and batch scoring. Run with:  pytest -v
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import decisioning as dec
from src.data_pipeline import LTI_HIGH_THRESHOLD, run_pipeline
from src.risk_model import build_pipeline, train_model

DATA_PATH = ROOT / "data" / "loan_data.csv"

APPLICANT = dict(
    applicant_income=5000.0, coapplicant_income=0.0, loan_amount=180000.0,
    loan_term_months=240, credit_history=0, dependents=2,
    employment_status="self_employed", property_area="rural",
    credit_score=610, late_payments_12m=1,
)


@pytest.fixture(scope="module")
def book():
    df, _ = run_pipeline(str(DATA_PATH))
    return df


@pytest.fixture(scope="module")
def model(book):
    return train_model(book)


# =========================================================================================
# AFFORDABILITY — the bug this release fixes
# =========================================================================================
def test_annual_loan_to_income_column_exists(book):
    assert "loan_to_annual_income" in book.columns


def test_annual_lti_is_monthly_lti_over_twelve(book):
    expected = book["loan_amount"] / (book["total_income"] * 12)
    assert np.allclose(book["loan_to_annual_income"], expected, atol=1e-3)


def test_affordability_flag_is_not_a_constant(book):
    """
    The v1 rule tested a monthly-income multiple against a threshold of 5, which fired for
    ~98% of the book — a constant masquerading as a rule. The corrected rule must actually
    discriminate.
    """
    share = float((book["loan_to_annual_income"] > LTI_HIGH_THRESHOLD).mean())
    assert 0.02 < share < 0.40, f"affordability flag fires on {share:.1%} of the book"


def test_risk_tiers_separate_on_approval(book):
    rates = book.groupby("risk_level", observed=True)["approved"].mean()
    assert rates["Low"] > rates["Medium"] > rates["High"], "risk tiers must rank monotonically"
    assert rates["Low"] - rates["High"] > 0.30


# =========================================================================================
# ENRICHMENT
# =========================================================================================
def test_enrich_application_adds_model_features():
    e = dec.enrich_application(APPLICANT)
    for field in ("total_income", "estimated_emi", "debt_to_income_ratio",
                  "loan_to_income_ratio", "loan_to_annual_income"):
        assert field in e
    assert e["total_income"] == 5000.0
    assert e["estimated_emi"] > 0


def test_enrich_frame_matches_enrich_application():
    frame = dec.enrich_frame(pd.DataFrame([APPLICANT]))
    single = dec.enrich_application(APPLICANT)
    for field in ("total_income", "debt_to_income_ratio", "loan_to_annual_income"):
        assert frame.iloc[0][field] == pytest.approx(single[field], rel=1e-6)


def test_enrich_handles_zero_income():
    e = dec.enrich_application({**APPLICANT, "applicant_income": 0.0,
                                "coapplicant_income": 0.0})
    # Zero income is unaffordable, not "no burden": ratios must be far above every cap.
    from src.data_pipeline import NO_INCOME_RATIO
    assert e["debt_to_income_ratio"] == NO_INCOME_RATIO
    assert e["loan_to_annual_income"] == NO_INCOME_RATIO
    assert e["loan_to_income_ratio"] == NO_INCOME_RATIO


# =========================================================================================
# REASON CODES
# =========================================================================================
def test_reason_codes_returned_and_ranked(model):
    reasons = dec.reason_codes(model.pipeline, APPLICANT, top_n=5)
    assert 0 < len(reasons) <= 5
    magnitudes = [abs(r.contribution) for r in reasons]
    assert magnitudes == sorted(magnitudes, reverse=True)
    assert all(r.direction in ("supports", "opposes") for r in reasons)


def test_reason_contributions_reconstruct_the_displayed_score(model):
    """
    The reviewed defect: reason codes used to explain only the logistic component while the
    displayed score was a 75/25 blend. They are now Shapley attributions of the FINAL score, so
    baseline + contributions must equal the displayed log-odds exactly. If this ever fails, the
    reasons shown to an applicant no longer explain the score they sit beside.
    """
    ex = dec.explain(model.pipeline, APPLICANT)
    total = sum(r.contribution for r in ex["reasons"])
    assert ex["baseline_logit"] + total == pytest.approx(ex["final_logit"], abs=1e-9)

    X = pd.DataFrame([dec.enrich_application(APPLICANT)])[dec.NUMERIC_FEATURES + dec.CATEGORICAL_FEATURES]
    shown = float(model.pipeline.predict_proba(X)[0, 1])
    assert ex["probability"] == pytest.approx(shown, abs=1e-9)


def test_reasons_are_business_factors_not_overlapping_columns(model):
    labels = [r.label for r in dec.explain(model.pipeline, APPLICANT)["reasons"]]
    assert len(labels) == len(set(labels)) == len(dec.REASON_GROUPS)
    assert not any("Debt-to-income" in l or "Monthly instalment" in l for l in labels)


def test_missing_credit_history_opposes_approval(model):
    reasons = dec.reason_codes(model.pipeline, {**APPLICANT, "credit_history": 0}, top_n=8)
    credit = next(r for r in reasons if "Credit history" in r.label)
    assert credit.direction == "opposes"


# =========================================================================================
# SENSITIVITY
# =========================================================================================
def test_sensitivity_sorted_and_bounded(model):
    sens = dec.sensitivity(model.pipeline, APPLICANT)
    assert not sens.empty
    assert list(sens["Shift"]) == sorted(sens["Shift"], reverse=True)
    assert sens["New probability"].between(0, 1).all()


def test_clean_credit_history_offered_only_when_missing(model):
    thin = dec.sensitivity(model.pipeline, {**APPLICANT, "credit_history": 0})
    thick = dec.sensitivity(model.pipeline, {**APPLICANT, "credit_history": 1})
    assert any("credit history" in c.lower() for c in thin["Change"])
    assert not any("credit history" in c.lower() for c in thick["Change"])


# =========================================================================================
# POLICY
# =========================================================================================
def test_policy_flags_and_explains_every_breach(book):
    tested = dec.apply_policy(book, dec.Policy())
    assert {"policy_pass", "breach_count", "breach_reason"}.issubset(tested.columns)
    assert (tested.loc[tested["policy_pass"], "breach_reason"] == "—").all()
    assert (tested.loc[~tested["policy_pass"], "breach_count"] >= 1).all()


def test_looser_policy_blocks_no_more_than_tighter(book):
    tight = dec.policy_impact(book, dec.Policy(max_dti=0.25, max_lti=2.0))
    loose = dec.policy_impact(book, dec.Policy(max_dti=0.80, max_lti=8.0,
                                               require_credit_history=False,
                                               exclude_unemployed=False))
    assert loose["blocked_n"] <= tight["blocked_n"]


def test_credit_score_and_late_payment_rules_bite_and_switch_off(book):
    off = dec.Policy(min_credit_score=300, max_late_payments=24)
    on = dec.Policy(min_credit_score=700, max_late_payments=0)
    t_off, t_on = dec.apply_policy(book, off), dec.apply_policy(book, on)
    assert not t_off["breach_reason"].str.contains("Credit score below minimum|late payments").any()
    assert (t_on.loc[book["credit_score"] < 700, "breach_reason"]
            .str.contains("Credit score below minimum")).all()
    assert (t_on.loc[book["late_payments_12m"] > 0, "breach_reason"]
            .str.contains("Too many late payments")).all()
    assert dec.policy_impact(book, on)["blocked_n"] >= dec.policy_impact(book, off)["blocked_n"]


def test_policy_describe_lists_credit_rules_only_when_active():
    assert any("Credit score of at least" in r for r in dec.Policy().describe())
    assert not any("Credit score" in r or "late payment" in r
                   for r in dec.Policy(min_credit_score=300, max_late_payments=24).describe())


def test_policy_separates_good_from_bad_credit(book):
    impact = dec.policy_impact(book, dec.Policy())
    assert impact["pass_approval_rate"] > impact["blocked_approval_rate"], (
        "a policy that does not separate approved from declined is not doing any work"
    )


def test_exceptions_queue_is_ordered_by_exposure(book):
    queue = dec.exceptions(book, dec.Policy(), limit=25)
    assert len(queue) <= 25
    assert (queue["breach_count"] >= 1).all()
    assert queue["breach_reason"].ne("—").all()


# =========================================================================================
# CUT-OFF TUNING
# =========================================================================================
def test_out_of_fold_probabilities_cover_the_book(book):
    proba = dec.out_of_fold_probabilities(build_pipeline(), book, folds=3)
    assert len(proba) == len(book)
    assert ((proba >= 0) & (proba <= 1)).all()


def test_raising_the_cutoff_approves_less(book):
    proba = dec.out_of_fold_probabilities(build_pipeline(), book, folds=3)
    sweep = dec.threshold_sweep(book["approved"].values, proba, steps=12)
    assert sweep["approved_share"].is_monotonic_decreasing
    assert sweep["false_approvals"].is_monotonic_decreasing


def test_confusion_at_totals_the_book(book):
    proba = dec.out_of_fold_probabilities(build_pipeline(), book, folds=3)
    cm = dec.confusion_at(book["approved"].values, proba, 0.5)
    assert sum(cm.values()) == len(book)


# =========================================================================================
# BATCH SCORING
# =========================================================================================
def test_score_frame_routes_every_row(model, book):
    intake = book.head(50)[dec.APPLICATION_FIELDS]
    scored = dec.score_frame(model.pipeline, intake, threshold=0.5)
    assert len(scored) == 50
    assert scored["approval_probability"].between(0, 1).all()
    assert scored["routing"].notna().all()
    assert set(scored["model_decision"]).issubset({"Approve", "Decline"})


def test_routing_agrees_with_probability(model, book):
    scored = dec.score_frame(model.pipeline, book.head(200)[dec.APPLICATION_FIELDS])
    fast = scored[scored["routing"] == "Fast-track"]["approval_probability"]
    declined = scored[scored["routing"] == "Decline"]["approval_probability"]
    if len(fast) and len(declined):
        assert fast.min() > declined.max()


# =========================================================================================
# PORTFOLIO COMPARISON
# =========================================================================================
def test_compare_to_book_is_zero_against_itself(book):
    stats = dec.compare_to_book(book, book)
    for metric in stats.values():
        assert metric["delta"] == pytest.approx(0.0, abs=1e-9)


def test_compare_to_book_reports_a_real_gap(book):
    rural = book[book["property_area"] == "rural"]
    stats = dec.compare_to_book(rural, book)
    assert stats["applications"]["value"] < stats["applications"]["baseline"]
    assert stats["approval_rate"]["baseline"] == pytest.approx(float(book["approved"].mean()))


# =========================================================================================
# CREDIT SCORE / LATE PAYMENTS DIRECTION — regression tests for the reported bug
# (more late payments used to RAISE the approval probability)
# =========================================================================================
from src.risk_model import predict_single_applicant


def _prob(model, **changes):
    return predict_single_applicant(model.pipeline, {**APPLICANT, **changes})[1]


@pytest.mark.parametrize("history", [0, 1])
def test_more_late_payments_never_raise_probability(model, history):
    probs = [_prob(model, credit_history=history, late_payments_12m=n) for n in range(0, 13)]
    assert all(b <= a + 1e-9 for a, b in zip(probs, probs[1:])), probs


@pytest.mark.parametrize("history", [0, 1])
def test_higher_credit_score_never_lowers_probability(model, history):
    probs = [_prob(model, credit_history=history, credit_score=s) for s in range(300, 851, 25)]
    assert all(b >= a - 1e-9 for a, b in zip(probs, probs[1:])), probs


def test_late_payments_and_score_have_correct_logistic_sign(model):
    fi = model.feature_importance.set_index("feature")["coefficient"]
    assert fi["credit_score"] >= 0
    assert fi["late_payments_12m"] <= 0


# =========================================================================================
# REGRESSION TESTS - the six system errors fixed in this version
# =========================================================================================
GOOD = dict(applicant_income=5000.0, coapplicant_income=0.0, loan_amount=120000.0, loan_term_months=360,
            credit_history=1, dependents=0, employment_status="salaried", property_area="urban",
            credit_score=700, late_payments_12m=0)


def test_fix1_zero_income_is_declined_not_scored_as_safe(model):
    from src.policy_store import Settings
    app = {**GOOD, "applicant_income": 0.0, "coapplicant_income": 0.0, "loan_amount": 50000.0}
    r = dec.assess(model.pipeline, app, Settings().policy(), 0.5)
    assert r["routing"] == "Decline" and not r["policy_pass"]
    assert "No income" in r["breaches"]
    assert r["probability"] < 0.10          # was ~0.89 when DTI was filled with 0


def test_fix2_affordability_checked_at_the_rate_actually_charged(model):
    from src.policy_store import Settings
    s = Settings()
    pol = s.policy()
    assert pol.assessment_rate == pytest.approx(s.base_rate + max(s.spread_review, s.spread_refer))
    # DTI 43.9% at 8.5% (passes the 45% cap) but 56.6% at 11.5% (does not).
    app = {**GOOD, "applicant_income": 2100.0}
    assert "DTI over cap" not in dec.assess(model.pipeline, app, dec.Policy(), 0.5)["breaches"]
    assert "DTI over cap" in dec.assess(model.pipeline, app, pol, 0.5)["breaches"]


def test_fix3_letter_claims_human_review_only_when_true():
    from src import reports
    auto = dec.adverse_action_text([], "C1")
    assert "A person reviewed" not in auto and "automated system" in auto
    assert "A person reviewed" in dec.adverse_action_text([], "C1", human_reviewed=True)
    assert reports.customer_letter_pdf(outcome="Decline", customer_ref="C1", reasons=[])[:4] == b"%PDF"


def test_fix4_declining_an_approve_band_score_needs_second_approval():
    from src import workflow
    why = workflow.review_requirements(outcome="Decline", loan_amount=1e5, authority_limit=2.5e5,
                                       policy_pass=True, routing="Fast-track")
    assert any("Declined against" in w for w in why)
    # a decline that the model also recommends needs no second approver
    assert not workflow.review_requirements(outcome="Decline", loan_amount=1e5, authority_limit=2.5e5,
                                            policy_pass=True, routing="Decline")


def test_fix5_term_counts_only_through_the_instalment(model):
    from src.risk_model import predict_single_applicant
    r, emi = 0.085 / 12, 922.7
    scores = []
    for t in (120, 240, 360):
        principal = emi * (1 - (1 + r) ** -t) / r          # same monthly instalment for every term
        scores.append(predict_single_applicant(model.pipeline, {**GOOD, "loan_amount": principal,
                                                                "loan_term_months": t})[1])
    assert max(scores) - min(scores) < 0.03
    # and a bigger loan can never raise the score
    p = [predict_single_applicant(model.pipeline, {**GOOD, "loan_amount": L})[1] for L in (60e3, 90e3, 120e3, 150e3)]
    assert all(a >= b - 1e-9 for a, b in zip(p, p[1:]))


def test_fix6_single_and_file_features_identical():
    app = {**GOOD, "credit_score": 300, "late_payments_12m": 24, "applicant_income": 0.0}
    one = dec.enrich_application(app)
    frame = dec.enrich_frame(pd.DataFrame([app])).iloc[0]
    for k in ("credit_payment_stress", "debt_to_income_ratio", "loan_to_income_ratio",
              "loan_to_annual_income", "income_per_dependent", "loan_burden_x_credit"):
        assert one[k] == pytest.approx(frame[k]), k
