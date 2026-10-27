"""Decisioning helpers for the new historical loan dataset."""
from __future__ import annotations
from dataclasses import dataclass, field
from itertools import combinations  # noqa: F401
from math import factorial
import numpy as np
import pandas as pd
from sklearn.model_selection import cross_val_predict, StratifiedKFold
from src.data_pipeline import (ASSUMED_ANNUAL_INTEREST_RATE, _emi, LTI_HIGH_THRESHOLD,
                               MIN_CREDIT_SCORE, MAX_LATE_PAYMENTS_12M, safe_ratio)
from src.risk_model import (CATEGORICAL_FEATURES, DOMAIN_FIELDS, NUMERIC_FEATURES, RAW_FIELDS, TARGET,
                            _logit, build_pipeline)

FEATURE_LABELS = {
    "applicant_income":"Applicant income", "coapplicant_income":"Co-applicant income",
    "loan_amount":"Loan amount", "loan_term_months":"Repayment term",
    "credit_history":"Credit history", "dependents":"Dependents", "credit_score":"Credit score",
    "late_payments_12m":"Late payments in last 12 months", "total_income":"Household income",
    "loan_to_income_ratio":"Loan size vs monthly income", "loan_to_annual_income":"Loan vs annual income",
    "estimated_emi":"Monthly instalment", "debt_to_income_ratio":"Debt-to-income ratio",
    "household_size":"Household size", "credit_score_band":"Credit-score band",
    "late_payment_rate":"12-month late-payment rate", "credit_payment_stress":"Credit/payment stress",
    "income_per_dependent":"Income per dependent", "loan_burden_x_credit":"Loan burden × credit weakness",
    "employment_status_self_employed":"Self-employed", "employment_status_unemployed":"Unemployed",
    "property_area_semiurban":"Semi-urban property", "property_area_urban":"Urban property",
    "property_area_rural":"Rural property",
}
APPLICATION_FIELDS = [
    "applicant_income","coapplicant_income","loan_amount","loan_term_months","credit_history",
    "dependents","employment_status","property_area","credit_score","late_payments_12m"
]


def _engineer_one(app: dict) -> dict:
    out = dict(app)
    income = float(out["applicant_income"]) + float(out["coapplicant_income"])
    emi = _emi(float(out["loan_amount"]), ASSUMED_ANNUAL_INTEREST_RATE, float(out["loan_term_months"]))
    out["total_income"] = income
    # FIX: zero income -> NO_INCOME_RATIO (unaffordable), not 0 (which meant "no burden").
    out["loan_to_income_ratio"] = safe_ratio(out["loan_amount"], income)
    out["loan_to_annual_income"] = safe_ratio(float(out["loan_amount"]) / 12, income)
    out["estimated_emi"] = emi
    out["debt_to_income_ratio"] = safe_ratio(emi, income)
    out["household_size"] = int(out["dependents"]) + 1 + int(float(out["coapplicant_income"]) > 0)
    score = float(out["credit_score"])
    out["credit_score_band"] = float(pd.cut(pd.Series([score]), [-np.inf,579,669,739,799,np.inf], labels=[0,1,2,3,4]).iloc[0])
    out["late_payment_rate"] = min(max(float(out["late_payments_12m"])/12.0,0),1)
    # FIX: same formula as enrich_frame / data_pipeline (no upper cap), so a single application
    # and the same row in a file always get identical features.
    out["credit_payment_stress"] = max(0.0, (850-score)/550.0 + out["late_payment_rate"])
    out["income_per_dependent"] = income / (int(out["dependents"]) + 1) if income else 0.0
    out["loan_burden_x_credit"] = out["loan_to_annual_income"] * max(0.0, 850-score) / 550.0
    return out


def enrich_application(app: dict) -> dict:
    return _engineer_one(app)


def enrich_frame(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["total_income"] = out["applicant_income"] + out["coapplicant_income"]
    out["loan_to_income_ratio"] = safe_ratio(out["loan_amount"], out["total_income"])
    out["loan_to_annual_income"] = safe_ratio(out["loan_amount"] / 12, out["total_income"])
    out["estimated_emi"] = out.apply(lambda r: _emi(r["loan_amount"], ASSUMED_ANNUAL_INTEREST_RATE, r["loan_term_months"]), axis=1)
    out["debt_to_income_ratio"] = safe_ratio(out["estimated_emi"], out["total_income"])
    out["household_size"] = out["dependents"] + 1 + (out["coapplicant_income"] > 0).astype(int)
    out["credit_score_band"] = pd.cut(out["credit_score"], [-np.inf,579,669,739,799,np.inf], labels=[0,1,2,3,4]).astype(float)
    out["late_payment_rate"] = (out["late_payments_12m"] / 12.0).clip(0,1)
    out["credit_payment_stress"] = ((850-out["credit_score"]) / 550.0 + out["late_payment_rate"]).clip(lower=0)
    out["income_per_dependent"] = out["total_income"] / (out["dependents"] + 1)
    out["loan_burden_x_credit"] = out["loan_to_annual_income"] * (850-out["credit_score"]).clip(lower=0) / 550.0
    return out


def _model_frame(enriched):
    return pd.DataFrame([enriched])[NUMERIC_FEATURES + CATEGORICAL_FEATURES] if isinstance(enriched, dict) else enriched[NUMERIC_FEATURES + CATEGORICAL_FEATURES]

@dataclass
class Reason:
    label: str
    contribution: float
    direction: str
    detail: str = ""


# ---------------------------------------------------------------------------------------
# REASON CODES - exact Shapley attribution of the FINAL (calibrated, blended) score
# ---------------------------------------------------------------------------------------
# What the officer types in, grouped into the business factors a customer can understand.
# Working at this level (not at the ~20 engineered columns) means a single cause is never
# split across several overlapping lines such as DTI / EMI / loan-to-income.
REASON_GROUPS: dict[str, list[str]] = {
    "Income": ["applicant_income", "coapplicant_income"],
    "Loan amount": ["loan_amount"],
    "Repayment term": ["loan_term_months"],
    "Credit history": ["credit_history"],
    "Dependents": ["dependents"],
    "Employment": ["employment_status"],
    "Property area": ["property_area"],
    "Credit score": ["credit_score"],
    "Late payments": ["late_payments_12m"],
}


def _group_detail(label: str, e: dict) -> str:
    d = {
        "Income": f"${e['applicant_income'] + e['coapplicant_income']:,.0f} per month household income",
        "Loan amount": f"${e['loan_amount']:,.0f} ({e['loan_to_annual_income']:.2f}x annual income, "
                       f"DTI {e['debt_to_income_ratio'] * 100:.0f}%)",
        "Repayment term": f"{int(e['loan_term_months'])} months",
        "Credit history": "on file" if e["credit_history"] == 1 else "none or adverse",
        "Dependents": f"{int(e['dependents'])}",
        "Employment": str(e["employment_status"]).replace("_", "-"),
        "Property area": str(e["property_area"]),
        "Credit score": f"score {e['credit_score']:.0f}",
        "Late payments": f"{e['late_payments_12m']:.0f} late payment(s) in 12 months",
    }
    return d[label]


def _coalition_scores(pipeline, app: dict) -> tuple[np.ndarray, list[str]]:
    """Log-odds of the final score for every subset of factors taken from the applicant (the
    rest set to the reference applicant): 2^9 = 512 rows scored in one vectorised call."""
    labels = list(REASON_GROUPS)
    n = len(labels)
    ref = pipeline.reference_
    rows = []
    for mask in range(1 << n):
        row = {k: ref[k] for k in RAW_FIELDS + CATEGORICAL_FEATURES}
        for i, lab in enumerate(labels):
            if mask >> i & 1:
                for f in REASON_GROUPS[lab]:
                    row[f] = app[f]
        rows.append(row)
    frame = enrich_frame(pd.DataFrame(rows))
    p = pipeline.predict_proba(frame[NUMERIC_FEATURES + CATEGORICAL_FEATURES])[:, 1]
    return _logit(p), labels


def explain(pipeline, app: dict) -> dict:
    """Shapley values (log-odds) that SUM EXACTLY, with the baseline, to the displayed score.

    baseline_logit - score of the reference (typical) applicant
    final_logit    - score of this applicant
    reasons        - one Reason per factor; sum(contribution) == final_logit - baseline_logit
    """
    v, labels = _coalition_scores(pipeline, app)
    n = len(labels)
    w = [factorial(k) * factorial(n - k - 1) / factorial(n) for k in range(n)]
    full = (1 << n) - 1
    phi = np.zeros(n)
    for i in range(n):
        bit = 1 << i
        for mask in range(1 << n):
            if mask & bit:
                continue
            k = bin(mask).count("1")
            phi[i] += w[k] * (v[mask | bit] - v[mask])
    e = enrich_application(app)
    reasons = [Reason(lab, float(c), "supports" if c >= 0 else "opposes", _group_detail(lab, e))
               for lab, c in zip(labels, phi)]
    reasons.sort(key=lambda r: abs(r.contribution), reverse=True)
    return {"baseline_logit": float(v[0]), "final_logit": float(v[full]), "reasons": reasons,
            "baseline_probability": float(1 / (1 + np.exp(-v[0]))),
            "probability": float(1 / (1 + np.exp(-v[full])))}


def reason_codes(pipeline, app: dict, top_n: int = 6) -> list[Reason]:
    """The factors that moved this application's FINAL score, largest first. Contributions are
    exact Shapley attributions of that score (not of one component model)."""
    return [r for r in explain(pipeline, app)["reasons"] if abs(r.contribution) > 1e-9][:top_n]


def adverse_reasons(reasons: list[Reason], n: int = 4) -> list[Reason]:
    """Principal reasons for an adverse-action notice: only factors that worked AGAINST approval."""
    return [r for r in reasons if r.direction == "opposes"][:n]


def adverse_action_text(reasons: list[Reason], applicant_ref: str = "", human_reviewed: bool = False) -> str:
    """Plain-language decline notice built from the principal adverse reasons.

    FIX: the notice used to state that a person reviewed the decision on EVERY letter, even for
    automatic declines (e.g. a hard-policy breach in a scored file). It now says so only when
    ``human_reviewed`` is True, i.e. a signed-in officer recorded the decision."""
    items = adverse_reasons(reasons)
    lines = [f"Re: your loan application{(' (' + applicant_ref + ')') if applicant_ref else ''}", "",
             "We are unable to approve your application at this time. The main reasons were:", ""]
    lines += [f"  {i}. {r.label}: {r.detail}" for i, r in enumerate(items, 1)] or \
             ["  1. The combination of factors on your application did not meet our lending criteria."]
    lines += ["", "You may ask us to review this decision, and you may reapply when your circumstances change."]
    lines += (["A person reviewed this decision; it was not made by an automated system alone."] if human_reviewed
              else ["This decision was produced by an automated system. You may ask for a person to review it."])
    return "\n".join(lines)


# ---------------------------------------------------------------------------------------
# OUT-OF-RANGE INPUTS, SCORE UNCERTAINTY
# ---------------------------------------------------------------------------------------
def out_of_range_fields(pipeline, app: dict) -> list[str]:
    """Inputs beyond the range of values the model was trained on (its score is extrapolation)."""
    out = []
    for f in DOMAIN_FIELDS:
        lo, hi = pipeline.domain_[f]
        v = float(app[f])
        if v < lo or v > hi:
            out.append(f"{FEATURE_LABELS.get(f, f)} {v:,.0f} (model saw {lo:,.0f}-{hi:,.0f})")
    return out


def out_of_range_frame(pipeline, df: pd.DataFrame) -> pd.Series:
    msgs = pd.Series("", index=df.index)
    for f in DOMAIN_FIELDS:
        lo, hi = pipeline.domain_[f]
        bad = (df[f] < lo) | (df[f] > hi)
        msgs[bad] = msgs[bad] + FEATURE_LABELS.get(f, f) + " outside training range; "
    return msgs.str.rstrip("; ")


def score_interval(model_result, p: float, window: int = 150, z: float = 1.645) -> tuple[float, float, int]:
    """90% interval for the true approval rate among applications that score like this one:
    the Wilson interval of the observed outcomes of the ``window`` nearest out-of-fold scores.
    Wide interval = few comparable cases = treat the point score with caution."""
    oof, y = np.asarray(model_result.oof_proba), np.asarray(model_result.oof_y)
    if len(oof) == 0:
        return float("nan"), float("nan"), 0
    k = min(window, len(oof))
    idx = np.argsort(np.abs(oof - p))[:k]
    obs = float(y[idx].mean())
    centre = (obs + z * z / (2 * k)) / (1 + z * z / k)
    half = z * np.sqrt(obs * (1 - obs) / k + z * z / (4 * k * k)) / (1 + z * z / k)
    return max(0.0, centre - half), min(1.0, centre + half), k


# ---------------------------------------------------------------------------------------
# ONE ROUTING RULE, used by every page
# ---------------------------------------------------------------------------------------
ROUTE_EDGES = [-.001, .35, .55, .75, 1.001]
ROUTE_LABELS = ["Decline", "Refer", "Review", "Fast-track"]


def route_one(p: float, policy_pass: bool, cutoff: float, out_of_range: bool = False,
              incomplete: bool = False) -> str:
    """The routing for a single score. Order of precedence:
    hard-policy breach -> Decline; incomplete/unscorable -> Refer; model band; then the cut-off
    is a floor for approving routes; and a score from outside the training range can never be
    Fast-track or Review (it is extrapolation) - at best Refer."""
    if not policy_pass:
        return "Decline"
    if incomplete:
        return "Refer"
    band = ROUTE_LABELS[int(np.digitize(p, ROUTE_EDGES[1:-1]))]
    if band in ("Review", "Fast-track") and p < cutoff:
        band = "Refer"
    if band in ("Review", "Fast-track") and out_of_range:
        band = "Refer"
    return band


def route_frame(p: pd.Series, policy_pass: pd.Series, cutoff: float, out_of_range: pd.Series | None = None,
                incomplete: pd.Series | None = None) -> pd.Series:
    oor = out_of_range if out_of_range is not None else pd.Series(False, index=p.index)
    inc = incomplete if incomplete is not None else pd.Series(False, index=p.index)
    return pd.Series([route_one(a, bool(b), cutoff, bool(c), bool(d))
                      for a, b, c, d in zip(p, policy_pass, oor, inc)], index=p.index)


def assess(pipeline, app: dict, policy: "Policy", cutoff: float, extras: dict | None = None) -> dict:
    """Score ONE application end to end - model score, hard policy, range check, routing -
    through exactly the same functions the batch page uses."""
    row = pd.DataFrame([{**app, **(extras or {})}])
    scored = score_frame(pipeline, row, threshold=cutoff, policy=policy, cutoff=cutoff)
    r = scored.iloc[0]
    return {
        "probability": float(r["approval_probability"]),
        "routing": str(r["routing"]),
        "policy_pass": bool(r["policy_pass"]),
        "breaches": [] if r["policy_pass"] else str(r["breach_reason"]).split(", "),
        "out_of_range": [m for m in str(r["range_warning"]).split("; ") if m],
        "enriched": r.to_dict(),
    }


def sensitivity(pipeline, app: dict) -> pd.DataFrame:
    base=float(pipeline.predict_proba(_model_frame(enrich_application(app)))[0,1])
    scenarios=[
        ("Reduce loan by 10%", {"loan_amount":app["loan_amount"]*.90}),
        ("Reduce loan by 25%", {"loan_amount":app["loan_amount"]*.75}),
        ("Extend term to 360 months", {"loan_term_months":360}),
        ("Improve credit score by 40 points", {"credit_score":min(850,app["credit_score"]+40)}),
        ("Remove 2 recent late payments", {"late_payments_12m":max(0,app["late_payments_12m"]-2)}),
        ("Add co-applicant at $2,000/mo", {"coapplicant_income":app["coapplicant_income"]+2000}),
    ]
    if app["credit_history"]==0: scenarios.insert(0,("Establish clean credit history",{"credit_history":1}))
    rows=[]
    for name,change in scenarios:
        if all(change.get(k)==app.get(k) for k in change): continue
        p=float(pipeline.predict_proba(_model_frame(enrich_application({**app,**change})))[0,1])
        rows.append({"Change":name,"New probability":p,"Shift":p-base})
    return pd.DataFrame(rows).sort_values("Shift",ascending=False).reset_index(drop=True) if rows else pd.DataFrame(columns=["Change","New probability","Shift"])


def score_frame(pipeline, df: pd.DataFrame, threshold=.5, policy: "Policy | None" = None, cutoff: float | None = None):
    """Score every row. When ``policy`` is given the hard rules are applied and routing is
    produced by ``route_frame`` - the same rule the single-application page uses."""
    enriched = enrich_frame(df)
    p = pipeline.predict_proba(enriched[NUMERIC_FEATURES + CATEGORICAL_FEATURES])[:, 1]
    out = enriched.copy()
    out["approval_probability"] = p
    out["model_decision"] = np.where(p >= threshold, "Approve", "Decline")
    out["range_warning"] = out_of_range_frame(pipeline, out)
    if policy is None:                                   # model-only view (analysis pages / tests)
        out["routing"] = pd.cut(p, ROUTE_EDGES, labels=ROUTE_LABELS)
        return out
    out = apply_policy(out, policy)
    cut = threshold if cutoff is None else cutoff
    out["routing"] = route_frame(out["approval_probability"], out["policy_pass"], cut,
                                 out["range_warning"].ne(""))
    out["final_decision"] = np.where(out["routing"].isin(["Fast-track", "Review"]), "Approve route",
                                     np.where(out["routing"] == "Refer", "Refer", "Decline"))
    return out


def out_of_fold_probabilities(pipeline, df, folds=5):
    X=df[NUMERIC_FEATURES+CATEGORICAL_FEATURES]; y=df[TARGET]
    cv=StratifiedKFold(n_splits=folds,shuffle=True,random_state=42)
    return cross_val_predict(pipeline,X,y,cv=cv,method="predict_proba",n_jobs=-1)[:,1]


def threshold_sweep(y_true,proba,steps=49):
    y_true=np.asarray(y_true).astype(int); rows=[]
    for t in np.linspace(.02,.98,steps):
        pred=(proba>=t).astype(int); tp=((pred==1)&(y_true==1)).sum(); fp=((pred==1)&(y_true==0)).sum(); fn=((pred==0)&(y_true==1)).sum(); tn=((pred==0)&(y_true==0)).sum()
        rows.append({"threshold":round(float(t),3),"approved_share":(tp+fp)/len(y_true),"precision":tp/(tp+fp) if tp+fp else np.nan,"recall":tp/(tp+fn) if tp+fn else np.nan,"accuracy":(tp+tn)/len(y_true),"false_approvals":int(fp),"missed_good":int(fn)})
    return pd.DataFrame(rows)


def confusion_at(y_true,proba,threshold):
    y_true=np.asarray(y_true).astype(int); pred=(proba>=threshold).astype(int)
    return {"tp":int(((pred==1)&(y_true==1)).sum()),"fp":int(((pred==1)&(y_true==0)).sum()),"fn":int(((pred==0)&(y_true==1)).sum()),"tn":int(((pred==0)&(y_true==0)).sum())}

@dataclass
class Policy:
    max_dti: float=.45; max_lti: float=3.5; require_credit_history: bool=True; exclude_unemployed: bool=True; max_loan_amount: float=5_000_000.
    # Credit-behaviour rules. Defaults match the risk-tier "severe" bands (score below 580,
    # 3+ late payments). Set min_credit_score to MIN_CREDIT_SCORE (300) or max_late_payments
    # to MAX_LATE_PAYMENTS_12M (24) to switch the rule off.
    min_credit_score: int=580; max_late_payments: int=2
    max_total_dti: float=.55   # new loan + existing monthly debts, over income (needs existing_monthly_debt)
    # FIX: the affordability caps used to be checked against an instalment at a fixed 8.5%, while
    # the customer is actually charged base rate + band spread (up to 11.5% by default). The caps
    # are now checked at ``assessment_rate`` - the highest rate this customer could be charged.
    # None keeps the old illustrative rate (ASSUMED_ANNUAL_INTEREST_RATE).
    assessment_rate: float | None = None
    rule_labels:list[str]=field(default_factory=list)
    def describe(self):
        rate = ASSUMED_ANNUAL_INTEREST_RATE if self.assessment_rate is None else self.assessment_rate
        r=["Applicant or co-applicant has income",f"Debt-to-income at or below {self.max_dti*100:.0f}% (instalment at {rate*100:.1f}%)",f"Loan no more than {self.max_lti:.1f}x annual income",f"Single loan no more than ${self.max_loan_amount:,.0f}"]
        if self.min_credit_score>MIN_CREDIT_SCORE:r.append(f"Credit score of at least {self.min_credit_score}")
        if self.max_late_payments<MAX_LATE_PAYMENTS_12M:r.append(f"No more than {self.max_late_payments} late payment{'s' if self.max_late_payments!=1 else ''} in the last 12 months")
        r.append(f"New instalment plus existing monthly debts at most {self.max_total_dti*100:.0f}% of income")
        if self.require_credit_history:r.append("Credit history on file")
        if self.exclude_unemployed:r.append("Applicant currently employed or self-employed")
        return r


def apply_policy(df,policy):
    out=df.copy()
    # Affordability at the rate the customer will really pay (see Policy.assessment_rate).
    rate = ASSUMED_ANNUAL_INTEREST_RATE if policy.assessment_rate is None else float(policy.assessment_rate)
    out["assessed_rate"]=rate
    out["assessed_emi"]=[_emi(float(a), rate, float(t)) for a, t in zip(out["loan_amount"], out["loan_term_months"])]
    out["assessed_dti"]=safe_ratio(out["assessed_emi"], out["total_income"])
    breaches={"No income":out["total_income"]<=0,
              "DTI over cap":out["assessed_dti"]>policy.max_dti,"Loan-to-income over cap":out["loan_to_annual_income"]>policy.max_lti,"Loan above single-exposure limit":out["loan_amount"]>policy.max_loan_amount}
    if policy.require_credit_history: breaches["No credit history"]=out["credit_history"]==0
    if policy.exclude_unemployed: breaches["Not employed"]=out["employment_status"]=="unemployed"
    if policy.min_credit_score>MIN_CREDIT_SCORE: breaches["Credit score below minimum"]=out["credit_score"]<policy.min_credit_score
    if policy.max_late_payments<MAX_LATE_PAYMENTS_12M: breaches["Too many late payments"]=out["late_payments_12m"]>policy.max_late_payments
    if "existing_monthly_debt" in out.columns:
        inc=out["total_income"].replace(0,np.nan)
        out["total_debt_service_ratio"]=((out["assessed_emi"]+out["existing_monthly_debt"].fillna(0))/inc).fillna(99.0)
        breaches["Total debt service over cap"]=out["total_debt_service_ratio"]>policy.max_total_dti
    # Informative flags, kept for reporting regardless of the hard-rule settings.
    out["credit_score_flag"]=out["credit_score"]<580
    out["late_payment_flag"]=out["late_payments_12m"]>=3
    bf=pd.DataFrame(breaches,index=out.index); out["policy_pass"]=~bf.any(axis=1); out["breach_count"]=bf.sum(axis=1).astype(int)
    out["breach_reason"]=bf.apply(lambda row:", ".join(c for c,h in row.items() if h) or "—",axis=1)
    return out


def policy_impact(df,policy):
    tested=apply_policy(df,policy); blocked=tested[~tested.policy_pass]; passed=tested[tested.policy_pass]
    return {"tested":tested,"blocked_n":len(blocked),"blocked_share":len(blocked)/len(tested) if len(tested) else 0.,"blocked_volume":float(blocked.loan_amount.sum()),"approved_but_blocked":int(blocked.approved.sum()) if len(blocked) else 0,"pass_approval_rate":float(passed.approved.mean()) if len(passed) else 0.,"blocked_approval_rate":float(blocked.approved.mean()) if len(blocked) else 0.,"top_breach":blocked.breach_reason.str.split(", ").explode().value_counts() if len(blocked) else pd.Series(dtype=int)}


def exceptions(df,policy,limit=100):
    tested=apply_policy(df,policy); flagged=tested[~tested.policy_pass].copy()
    if flagged.empty:return flagged
    flagged["exposure_rank"]=flagged.loan_amount*flagged.breach_count
    cols=["loan_amount","total_income","debt_to_income_ratio","loan_to_annual_income","credit_history","credit_score","late_payments_12m","employment_status","property_area","risk_level","breach_count","breach_reason","approved"]
    return flagged.sort_values("exposure_rank",ascending=False)[cols].head(limit)


def compare_to_book(filtered: pd.DataFrame, book: pd.DataFrame) -> dict:
    """
    Headline metrics for the current selection, each compared with the whole book.

    Every entry is a dict with:
        value    - the metric for the filtered selection
        baseline - the same metric for the whole book
        delta    - value - baseline (fractions for rates, so 0.04 == +4.0pp)

    Against the whole book every delta is exactly zero.
    """
    def _num(x) -> float:
        x = float(x)
        return 0.0 if np.isnan(x) else x

    def metric(fn) -> dict:
        v = _num(fn(filtered)) if len(filtered) else 0.0
        b = _num(fn(book)) if len(book) else 0.0
        return {"value": v, "baseline": b, "delta": v - b}

    return {
        "applications": metric(len),
        "exposure": metric(lambda d: d["loan_amount"].sum()),
        "approval_rate": metric(lambda d: d["approved"].mean()),
        "avg_dti": metric(lambda d: d["debt_to_income_ratio"].mean()),
        "high_risk_share": metric(lambda d: (d["risk_level"] == "High").mean()),
        "avg_loan": metric(lambda d: d["loan_amount"].mean()),
        "median_loan": metric(lambda d: d["loan_amount"].median()),
        "median_income": metric(lambda d: d["total_income"].median()),
    }
