"""Score an application — the underwriting workspace.

This is the page the product exists for. Everything else describes the book; this decides
one case. It scores live as the officer types, and it never returns a number without the
reasons behind it.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src import decisioning as dec
from src import risk_economics as econ
from src import ui, workflow
from src import reports
from src.deps import MissingLibrary
from views._docs import render_documents
from src.data_pipeline import LOCAL_TZ, LTI_HIGH_THRESHOLD, to_local, today_local
from src.security import esc
from src.state import ctx
from src import auth, audit
from src import loanbook as lb

TERMS = [60, 120, 180, 240, 300, 360, 420, 480]

ROUTING = {
    "Fast-track": ("Route to fast-track", ui.LOW,
                   "Scores in the range the book approves almost uniformly."),
    "Review": ("Route to standard review", "#5E9E7E",
               "Inside normal approval territory, but not without a look."),
    "Refer": ("Refer to a senior officer", ui.MED,
              "The book is genuinely split on profiles like this one."),
    "Decline": ("Prepare a decline", ui.HIGH,
                "Scores in the range the book declines almost uniformly."),
}


def render() -> None:
    c = ctx()

    ui.page_header(
        "Score an application",
        "Enter an application to get a probability, the reasons behind it, and what "
        "would have to change to move it. Hard policy rules are applied exactly as they are "
        "on Score a file.",
        eyebrow="Decisioning",
    )

    app, extras = _form(c.book)
    if app is None:
        todo = missing_fields()
        done = len(REQUIRED) - len(todo)
        st.progress(done / len(REQUIRED), text=f"{done} of {len(REQUIRED)} required fields filled in")
        ui.note("The score, the reasons and the Save button appear once every required field is filled in. "
                "Still to fill in: <b>" + esc(", ".join(todo)) + "</b>.",
                title="Fill in the application", tone="info")
        return
    enriched = dec.enrich_application(app)

    if enriched["total_income"] <= 0:
        ui.note("Enter an applicant income to score this application.",
                title="Waiting on income", tone="warn")
        return

    # One call: model score + hard policy + range check + routing, through the same functions
    # the batch page uses, so the two pages cannot disagree about the same application.
    result = dec.assess(c.model.pipeline, app, c.policy, c.cutoff, extras)
    proba, routing = result["probability"], result["routing"]
    interval = dec.score_interval(c.model, proba)

    _policy_banner(c, result)
    _decision(proba, c.cutoff, routing, interval, result)
    _affordability(enriched)
    _economics(c, app, extras, enriched, result)
    st.markdown("")

    explanation = dec.explain(c.model.pipeline, app)
    left, right = st.columns([1.12, 1], gap="large")
    with left:
        _reasons(explanation)
    with right:
        _sensitivity(c.model.pipeline, app, proba)

    _comparables(c.book, enriched)
    _record(c, app, extras, enriched, result, interval, explanation)
    ui.disclaimer()


def _policy_banner(c, result: dict) -> None:
    if not result["policy_pass"]:
        ui.note("This application breaches hard policy: <b>" + esc("; ".join(result["breaches"])) + "</b>. "
                "It is routed to <b>Decline</b> whatever the model score. An officer can still record an "
                "approval, but only as a policy exception that a second approver must sign off.",
                title=f"Policy v{c.policy_version}: breach", tone="stop")
    if result["out_of_range"]:
        ui.note("Beyond the range of applications the model was trained on: <b>" + esc("; ".join(result["out_of_range"]))
                + "</b>. The score is an extrapolation, so it is capped at <b>Refer</b> and an approval "
                "needs a second approver.", title="Outside the model's experience", tone="warn")


# -----------------------------------------------------------------------------------------
def _history(ref: str, application_date: str | None) -> None:
    """Earlier decisions for the same customer reference, so a repeat applicant is visible."""
    if not (ref or "").strip():
        return
    h = workflow.customer_history(ref)
    if h.empty:
        st.caption("No earlier decisions for this reference.")
        return
    last = pd.to_datetime(h["created_at"].iloc[0], utc=True).tz_convert(LOCAL_TZ)
    gap = (pd.Timestamp(application_date) - last.tz_localize(None).normalize()).days if application_date else None
    msg = (f"<b>{len(h)}</b> earlier decision(s) for this reference. Latest: <b>{esc(h['outcome'].iloc[0])}</b> "
           f"on {last:%d/%m/%Y}" + (f" ({gap} days before this application)" if gap is not None and gap >= 0 else "") + ".")
    ui.note(msg, title="Repeat applicant", tone="info")
    show = h.assign(created_at=to_local(h["created_at"]))
    show = show.rename(columns={"created_at": "decided (local time)", "application_date": "received"})
    ui.table(show.style.format({"loan_amount": "{:,.0f}"}), hide_index=True)


# -----------------------------------------------------------------------------------------
# Every field starts empty: the officer types each value from the application form, so nothing
# is scored on a number the system made up. "Fill with an example" puts in a practice case.
REQUIRED = {  # widget key -> label shown in the "still to fill in" list
    "uw_income": "Monthly income", "uw_deps": "Dependents", "uw_amount": "Loan amount",
    "uw_term": "Term", "uw_product": "Product", "uw_credit": "Credit history",
    "uw_emp": "Employment", "uw_area": "Property area", "uw_score": "Credit score",
    "uw_late": "Late payments - last 12 months",
}
OPTIONAL = ("uw_coincome", "uw_exdebt", "uw_collateral")      # blank = 0
EXAMPLE = {"uw_income": 5_000, "uw_coincome": 0, "uw_deps": 0, "uw_amount": 120_000, "uw_term": 360,
           "uw_product": lb.PRODUCTS[0], "uw_exdebt": 0, "uw_collateral": 0, "uw_credit": 1,
           "uw_emp": "salaried", "uw_area": "urban", "uw_score": 700, "uw_late": 0}


def _fill_example() -> None:
    for k, v in EXAMPLE.items():
        st.session_state[k] = v


def _clear_form() -> None:
    for k in EXAMPLE:
        st.session_state[k] = None
    for k in ("uw_ref", "uw_rationale"):
        st.session_state[k] = ""
    st.session_state.pop("uw_saved", None)


def missing_fields() -> list[str]:
    return [label for key, label in REQUIRED.items() if st.session_state.get(key) is None]


def _form(book: pd.DataFrame) -> tuple[dict | None, dict]:
    ui.section("Application", "Fill in every field from the customer's application form. Fields marked "
                              "(optional) can stay blank and count as 0.")
    t1, t2, _ = st.columns([1.25, 0.8, 3], gap="small")
    t1.button("Fill with an example", key="uw_fill_example", on_click=_fill_example,
              help="Puts in a practice applicant so you can see how the page works.")
    t2.button("Clear form", key="uw_clear", on_click=_clear_form)

    a, b, c = st.columns(3, gap="medium")
    num = dict(value=None, placeholder="Type a number")

    with a:
        st.markdown("**Applicant**")
        applicant_income = st.number_input(
            "Monthly income", min_value=0, max_value=200_000, step=250,
            key="uw_income", help="Gross monthly income of the primary applicant.", **num,
        )
        coapplicant_income = st.number_input(
            "Co-applicant monthly income (optional)", min_value=0, max_value=200_000, step=250,
            key="uw_coincome", help="Leave blank or enter 0 if there is no co-applicant.",
            value=None, placeholder="Blank = 0",
        )
        dependents = st.number_input(
            "Dependents", min_value=0, max_value=10, step=1, key="uw_deps", **num,
        )

    with b:
        st.markdown("**Facility**")
        loan_amount = st.number_input(
            "Loan amount", min_value=1_000, max_value=5_000_000, step=5_000,
            key="uw_amount", **num,
        )
        loan_term_months = st.selectbox(
            "Term", TERMS, index=None, key="uw_term", placeholder="Choose a term",
            format_func=lambda m: f"{m} months  ({m // 12} years)",
        )
        product = st.selectbox("Product", lb.PRODUCTS, index=None, key="uw_product",
                               placeholder="Choose a product")
        today = today_local().date()
        app_date = st.date_input(
            "Application received", value=today, max_value=today, key="uw_app_date", format="DD/MM/YYYY",
            help="The day the bank received the application (Phnom Penh time). Recorded with the "
                 "decision for time-to-decision and period reporting. It does not change the score.")
        existing_debt = st.number_input(
            "Existing monthly debt payments (optional)", min_value=0, max_value=1_000_000, step=50,
            key="uw_exdebt", value=None, placeholder="Blank = 0",
            help="Instalments the applicant already pays on other loans/cards. "
                 "Without this, debt-to-income is a floor, not the real figure.")
        collateral = st.number_input(
            "Collateral value (optional)", min_value=0, max_value=50_000_000, step=5_000,
            key="uw_collateral", value=None, placeholder="Blank = 0 (unsecured)",
            help="Appraised value of the security offered (blank or 0 = unsecured).")
        st.caption("Model instalment estimate assumes 8.5% p.a.; the price suggestion below uses the policy rate.")

    with c:
        st.markdown("**Profile**")
        credit_history = st.selectbox(
            "Credit history", [1, 0], index=None, key="uw_credit", placeholder="Choose one",
            format_func=lambda v: "On file" if v == 1 else "None or adverse",
        )
        employment_status = st.selectbox(
            "Employment", ["salaried", "self_employed", "unemployed"], index=None, key="uw_emp",
            placeholder="Choose one", format_func=lambda v: v.replace("_", "-").title(),
        )
        property_area = st.selectbox(
            "Property area", ["urban", "semiurban", "rural"], index=None, key="uw_area",
            placeholder="Choose one", format_func=lambda v: v.title(),
        )
        credit_score = st.number_input(
            "Credit score", min_value=300, max_value=850, step=5,
            key="uw_score", help="Credit bureau score, 300 to 850.", **num,
        )
        late_payments_12m = st.number_input(
            "Late payments - last 12 months", min_value=0, max_value=24, step=1,
            key="uw_late", help="Number of late-payment events in the previous 12 months. Enter 0 if none.",
            **num,
        )

    extras = dict(existing_monthly_debt=float(existing_debt or 0), collateral_value=float(collateral or 0),
                  product=product, application_date=app_date.isoformat())
    if missing_fields():
        return None, extras
    return dict(
        applicant_income=float(applicant_income),
        coapplicant_income=float(coapplicant_income or 0),
        loan_amount=float(loan_amount),
        loan_term_months=int(loan_term_months),
        credit_history=int(credit_history),
        dependents=int(dependents),
        employment_status=employment_status,
        property_area=property_area,
        credit_score=int(credit_score),
        late_payments_12m=int(late_payments_12m),
    ), extras


# -----------------------------------------------------------------------------------------
def _decision(proba: float, cutoff: float, routing: str, interval, result: dict) -> None:
    action, badge_color, rationale = ROUTING[routing]
    if not result["policy_pass"]:
        rationale = "A hard policy rule is breached - the model score cannot override it."
    elif result["out_of_range"]:
        rationale = "The inputs are outside the data the model learned from - a person must look."
    elif proba < cutoff and routing == "Refer":
        rationale = f"Below the {cutoff:.0%} cut-off, so it cannot be routed as an approval."

    rail = ui.band_rail(
        proba, ui.PROBABILITY_BANDS,
        caption=f"<span>decline · refer · review · fast-track</span>"
                f"<b>cut-off {cutoff * 100:.0f}%</b>",
    )
    lo, hi, n = interval
    rng = (f'<div class="cd-decision-sub">90% range for applications scored like this: '
           f'{lo * 100:.0f}% to {hi * 100:.0f}% (based on {n} comparable scores)</div>') if n else ""

    st.markdown(
        f'<div class="cd-decision" style="border-left:4px solid {badge_color};">'
        f'<div style="min-width:150px;">'
        f'<div class="cd-decision-prob">{proba * 100:.0f}<span style="font-size:1.2rem;">%</span></div>'
        f'<div class="cd-decision-sub">approval probability</div></div>'
        f'<div style="flex:1;min-width:280px;">'
        f'<div class="cd-decision-badge" style="color:{badge_color};">{action}</div>'
        f'<div class="cd-decision-sub">{esc(rationale)}</div>{rng}'
        f'<div style="margin-top:0.5rem;">{rail}</div>'
        f"</div></div>",
        unsafe_allow_html=True,
    )


def _affordability(e: dict) -> None:
    st.markdown("")
    cols = st.columns(4, gap="small")
    dti = e["debt_to_income_ratio"]
    lti = e["loan_amount"] / (e["total_income"] * 12) if e["total_income"] else 0

    with cols[0]:
        ui.kpi("Monthly instalment", ui.money(e["estimated_emi"], 0),
               foot=f"on {ui.money(e['loan_amount'], 0)} over {int(e['loan_term_months'])} months")
    with cols[1]:
        label, _ = ui.band_label(dti, ui.DTI_BANDS)
        ui.kpi("Debt-to-income", ui.pct(dti),
               rail=ui.band_rail(dti, ui.DTI_BANDS, caption=f"<span>{label}</span>"))
    with cols[2]:
        over = lti > LTI_HIGH_THRESHOLD
        ui.kpi("Loan to annual income", f"{lti:.2f}x",
               delta="over 3.5x" if over else "within 3.5x",
               delta_dir="down" if over else "up",
               foot=f"{ui.money(e['total_income'] * 12, 0)} annual household income")
    with cols[3]:
        residual = e["total_income"] - e["estimated_emi"]
        ui.kpi("Income after instalment", ui.money(residual, 0),
               foot=f"supports a household of {int(e['dependents']) + 1 + (1 if e['coapplicant_income'] else 0)}")


def _economics(c, app: dict, extras: dict, e: dict, result: dict) -> None:
    """Price, instalment and expected loss for this loan under the policy's assumptions."""
    ui.section("Price and expected loss",
               "From the assumptions on the Policy page - default probability per band, collateral haircut, "
               "unsecured LGD. These are assumptions, not model output: the approval model does not predict default.")
    inc = e["total_income"]
    tds = (e["estimated_emi"] + extras["existing_monthly_debt"]) / inc if inc else 0
    pv = econ.pricing_view(app["loan_amount"], app["loan_term_months"], result["routing"], extras["collateral_value"], c.settings)
    cols = st.columns(5, gap="small")
    with cols[0]:
        ui.kpi("Total debt service", ui.pct(tds),
               delta=("over cap" if tds > c.settings.max_total_dti else "within cap"),
               delta_dir="down" if tds > c.settings.max_total_dti else "up",
               foot=f"new instalment + existing debts; cap {c.settings.max_total_dti:.0%}")
    if pv is None:
        with cols[1]:
            ui.kpi("Suggested rate", "No offer", foot="the routing is Decline")
        return
    el = pv["el"]
    with cols[1]:
        ui.kpi("Suggested rate", ui.pct(pv["rate"], 2), foot=f"base {c.settings.base_rate:.2%} + risk spread")
    with cols[2]:
        ui.kpi("Instalment at that rate", ui.money(pv["emi"], 0), foot=f"over {app['loan_term_months']} months")
    with cols[3]:
        ui.kpi("Expected loss", ui.money(el["el"], 0), foot=f"PD {el['pd']:.1%} x LGD {el['lgd']:.0%} x {ui.money(el['ead'], 0)}")
    with cols[4]:
        ui.kpi("Rate after expected loss", ui.pct(pv["risk_adjusted_rate"], 2),
               foot="suggested rate minus one year's expected loss")
    st.session_state["_uw_pricing"] = pv


# -----------------------------------------------------------------------------------------
def _reasons(explanation: dict) -> None:
    ui.section("Why it scored this way")
    base, final = explanation["baseline_probability"], explanation["probability"]
    st.markdown(
        f'<p class="cd-lede" style="font-size:0.865rem;">A typical applicant in this book scores '
        f'<b>{base * 100:.0f}%</b>; this application scores <b>{final * 100:.0f}%</b>. Each line is how far '
        f'that factor moved the score from the typical applicant (Shapley attribution of the final, '
        f'calibrated score). The lines add up exactly to the move, so these are the reasons to use '
        f'in an adverse-action notice.</p>',
        unsafe_allow_html=True,
    )

    reasons = [r for r in explanation["reasons"] if abs(r.contribution) > 0.005][:6]
    if not reasons:
        return
    widest = max(abs(r.contribution) for r in reasons) or 1.0

    rows = []
    for r in reasons:
        color = ui.LOW if r.direction == "supports" else ui.HIGH
        width = abs(r.contribution) / widest * 100
        verb = "supports approval" if r.direction == "supports" else "works against approval"
        offset = 50 if r.direction == "supports" else 50 - width / 2
        rows.append(
            f'<div class="cd-reason">'
            f'<div><div class="cd-reason-label">{esc(r.label)}</div>'
            f'<div class="cd-reason-detail">{esc(r.detail or verb)}</div></div>'
            f'<div style="text-align:right;color:{color};font-weight:600;font-size:0.855rem;">'
            f'{r.contribution:+.2f}</div>'
            f'<div class="cd-reason-bar">'
            f'<span style="margin-left:{offset:.1f}%;width:{width / 2:.1f}%;background:{color};"></span>'
            f"</div></div>"
        )
    st.markdown(f'<div class="cd-panel">{"".join(rows)}</div>', unsafe_allow_html=True)
    shown = sum(r.contribution for r in reasons)
    total = explanation["final_logit"] - explanation["baseline_logit"]
    st.caption(
        f"Log-odds contributions. All nine factors sum to {total:+.2f} (the move from "
        f"{base * 100:.0f}% to {final * 100:.0f}%); the lines shown sum to {shown:+.2f}."
    )


def _sensitivity(pipeline, app: dict, base: float) -> None:
    ui.section("What would change the answer")
    st.markdown(
        f'<p class="cd-lede" style="font-size:0.865rem;">The same application re-scored under '
        f'changes an officer could realistically discuss with the applicant.</p>',
        unsafe_allow_html=True,
    )

    sens = dec.sensitivity(pipeline, app)
    if sens.empty:
        return

    fig = go.Figure()
    fig.add_bar(
        y=sens["Change"], x=sens["Shift"] * 100, orientation="h",
        marker_color=[ui.LOW if v > 0 else ui.HIGH for v in sens["Shift"]],
        marker_line_width=0, opacity=0.9,
        text=[f"{v * 100:+.1f}pp" for v in sens["Shift"]],
        textposition="outside", textfont=dict(size=11, color=ui.INK),
        customdata=(sens["New probability"] * 100).round(1),
        hovertemplate="%{y}<br>Shift %{x:+.1f}pp<br>New score %{customdata}%<extra></extra>",
    )
    fig.add_vline(x=0, line_color=ui.BORDER_STRONG, line_width=1)
    span = max(abs(sens["Shift"].max()), abs(sens["Shift"].min()), 0.05) * 100
    fig.update_layout(
        xaxis=dict(title=f"Change from {base * 100:.0f}%", ticksuffix="pp",
                   range=[-span * 1.45, span * 1.45], zeroline=False),
        yaxis=dict(title="", autorange="reversed"),
        bargap=0.4,
    )
    ui.chart(fig, height=max(230, 58 * len(sens)))

    best = sens.iloc[0]
    if best["Shift"] > 0.02:
        ui.note(
            f"<b>{best['Change']}</b> is the single largest available move, taking the score "
            f"to {best['New probability'] * 100:.0f}%. Structuring conversations start here.",
            tone="info",
        )


# -----------------------------------------------------------------------------------------
def _comparables(book: pd.DataFrame, e: dict) -> None:
    """What did the book actually do with applications like this one?"""
    ui.section("How the book treated similar applications",
               "Historical outcomes for applications with the same credit history and "
               "employment, within a comparable affordability band.")

    lo, hi = e["debt_to_income_ratio"] - 0.06, e["debt_to_income_ratio"] + 0.06
    peers = book[
        (book["credit_history"] == e["credit_history"])
        & (book["employment_status"] == e["employment_status"])
        & (book["debt_to_income_ratio"].between(lo, hi))
    ]

    if len(peers) < 12:
        peers = book[
            (book["credit_history"] == e["credit_history"])
            & (book["debt_to_income_ratio"].between(lo - 0.06, hi + 0.06))
        ]
        basis = "same credit history and a similar debt-to-income ratio"
    else:
        basis = "same credit history, same employment type and a similar debt-to-income ratio"

    if peers.empty:
        ui.note("No comparable applications in the book.", tone="warn")
        return

    cols = st.columns(4, gap="small")
    with cols[0]:
        ui.kpi("Comparable applications", f"{len(peers):,}", foot=basis)
    with cols[1]:
        ui.kpi("Approved historically", ui.pct(float(peers["approved"].mean())))
    with cols[2]:
        ui.kpi("Median loan", ui.money(peers["loan_amount"].median(), 0),
               foot=f"this application {ui.money(e['loan_amount'], 0)}")
    with cols[3]:
        pctile = float((peers["loan_amount"] < e["loan_amount"]).mean())
        ui.kpi("Loan size percentile", f"{pctile * 100:.0f}th",
               foot="among comparable applications")


# -----------------------------------------------------------------------------------------
CHECKLIST = [
    ("identity", "Identity and KYC / sanctions screening completed"),
    ("income", "Income verified against documents"),
    ("bureau", "Credit bureau file checked (score and liabilities on the form match)"),
    ("liabilities", "Existing debts and collateral reviewed outside this model"),
]


def _fingerprint(app: dict, ref: str, outcome: str) -> str:
    return "|".join(f"{k}={v}" for k, v in sorted(app.items())) + f"|{ref}|{outcome}"


def _record(c, app: dict, extras: dict, e: dict, result: dict, interval, explanation: dict) -> None:
    user = auth.current_user()
    ui.section("Decision record",
               "Saving writes the decision, the full inputs, the reasons, the score, the policy and model "
               "versions and a tamper-evident audit entry in one step. Nothing is recorded until you save.")

    a, b = st.columns([1, 1.6], gap="medium")
    with a:
        st.text_input("Officer", value=f"{user.display_name} ({user.username})", disabled=True)
        ref = st.text_input("Customer / case reference", key="uw_ref", max_chars=60,
                            placeholder="Internal ID - not a name",
                            help="Use your core-banking customer or case number so the case can be traced.")
        _history(ref, extras.get("application_date"))
        outcome = st.radio(
            "Decision", ["Approve", "Approve with conditions", "Refer", "Decline"],
            key="uw_outcome", horizontal=False,
        )
    with b:
        rationale = st.text_area(
            "Rationale", key="uw_rationale", height=130,
            placeholder="Where your judgement differs from the model or policy, record why. "
                        "Required for referrals, policy exceptions, overrides and large loans.",
        )

    approving = outcome in workflow.APPROVING
    checks = {}
    if approving:
        st.markdown("**Verification before approval**")
        for key, label in CHECKLIST:
            checks[key] = st.checkbox(label, key=f"uw_chk_{key}")

    why = workflow.review_requirements(
        outcome=outcome, loan_amount=app["loan_amount"], authority_limit=c.settings.officer_authority_limit,
        policy_pass=result["policy_pass"], routing=result["routing"], out_of_range=bool(result["out_of_range"]))
    if why:
        ui.note("This decision will wait for a second approver (a Risk Manager or Administrator who is "
                "not you): <b>" + esc("; ".join(why)) + "</b>.", title="Second approval required", tone="warn")

    fp = _fingerprint({**app, **{k: v for k, v in extras.items()}}, ref, outcome)
    saved = st.session_state.get("uw_saved")
    already = bool(saved and saved["fingerprint"] == fp)
    if st.button("Save decision", type="primary", disabled=already or not ref.strip()):
        try:
            res = workflow.save_decision(
                username=user.username, role=user.role, customer_ref=ref.strip(), outcome=outcome,
                loan_amount=app["loan_amount"], probability=result["probability"],
                score_low=interval[0], score_high=interval[1], routing=result["routing"], cutoff=c.cutoff,
                policy_version=c.policy_version, model_version=c.model_version,
                policy_pass=result["policy_pass"], breaches=result["breaches"], inputs={**app, **extras},
                reasons=[{"label": r.label, "contribution": round(r.contribution, 4),
                          "direction": r.direction, "detail": r.detail} for r in explanation["reasons"]],
                rationale=rationale, checklist=checks if approving else {},
                authority_limit=c.settings.officer_authority_limit,
                out_of_range=bool(result["out_of_range"]))
            st.session_state["uw_saved"] = {"fingerprint": fp, "app_id": res.application_id,
                                            "pending": res.needs_review, "why": res.review_reasons}
            _push_decision_result(res, user, ref.strip(), outcome, app, extras, result, interval,
                                  explanation, rationale, c)
            st.rerun()
        except (ValueError, audit.AuditError) as exc:
            st.error(str(exc))
    if not ref.strip():
        st.caption("Enter a case reference to enable saving.")

    if already:
        state = ("Pending second approval - it appears in the Decision queue for a reviewer."
                 if saved["pending"] else "Final.")
        st.success(f"Saved as **{saved['app_id']}**. {state}")
        record = _render_record(saved["app_id"], c, app, e, result, interval, explanation, user,
                                outcome, rationale, ref)
        pv = st.session_state.get("_uw_pricing")
        reasons_json = [{"label": r.label, "contribution": r.contribution, "detail": r.detail}
                        for r in explanation["reasons"]]
        d1, d2, d3 = st.columns(3)
        if not reports.HAVE_PDF:
            ui.note(str(MissingLibrary("reportlab")), title="PDF downloads unavailable", tone="warn")
        if reports.HAVE_PDF:
          d1.download_button("Decision record (PDF)", reports.decision_pdf(
            app_id=saved["app_id"], customer_ref=ref, officer=f"{user.display_name} ({user.username})",
            outcome=outcome, probability=result["probability"], interval=interval, routing=result["routing"],
            policy_version=c.policy_version, model_version=c.model_version, policy_pass=result["policy_pass"],
            breaches=result["breaches"], inputs={**app, **extras}, reasons=reasons_json, rationale=rationale,
            loan_econ=pv), file_name=f"{saved['app_id']}.pdf", mime="application/pdf")
        d2.download_button("Decision record (Markdown)", record.encode("utf-8"),
                           file_name=f"{saved['app_id']}.md", mime="text/markdown")
        adverse = [f"{r.label}: {r.detail}" for r in dec.adverse_reasons(explanation["reasons"])]
        terms = (f"Amount {app['loan_amount']:,.0f}, term {app['loan_term_months']} months"
                 + (f", indicative rate {pv['rate']:.2%}" if pv else "")) if outcome != "Decline" else ""
        if reports.HAVE_PDF:
          d3.download_button("Customer letter (PDF)", reports.customer_letter_pdf(
            outcome=outcome, customer_ref=ref, reasons=adverse, terms=terms,
            human_reviewed=True),   # only offered after a signed-in officer saved the decision
            file_name=f"{saved['app_id']}_letter.pdf", mime="application/pdf")
        render_documents(saved["app_id"], key="uw_docs")


def _push_decision_result(res, user, ref, outcome, app, extras, result, interval, explanation, rationale, c) -> None:
    """The result window after Save decision: a decision slip plus the full record and the customer letter."""
    from views import _result
    pv = st.session_state.get("_uw_pricing")
    pending = bool(res.needs_review)
    if pending:
        tone, status = "warn", "Saved - waiting for a second approver"
        steps = ["A Risk Manager or Administrator (not you) reviews it in Decision queue.",
                 "They approve, reject or return it to you with a comment.",
                 "Once approved, create the loan in Loan book > Add a loan."]
    elif outcome in workflow.APPROVING:
        tone, status = "good", f"Saved - {outcome} (final)"
        steps = ["Give the customer the approval letter.", "Create the loan in Loan book > Add a loan."]
    elif outcome == "Decline":
        tone, status = "stop", "Saved - Decline (final)"
        steps = ["Give the customer the decline letter: it lists the main reasons and how to ask for a review."]
    else:
        tone, status = "info", f"Saved - {outcome}"
        steps = []
    rows = [("Customer / case", ref), ("Decision", outcome), ("Loan amount", f"{app['loan_amount']:,.2f}"),
            ("Term", f"{app['loan_term_months']} months"),
            ("Model score", f"{result['probability'] * 100:.1f}% (range {interval[0] * 100:.0f}-{interval[1] * 100:.0f}%)"),
            ("Routing", result["routing"]),
            ("Hard policy", "pass" if result["policy_pass"] else "BREACH: " + "; ".join(result["breaches"])),
            ("Status", "Pending second approval" if pending else "Final")]
    if pending:
        rows.append(("Second approval needed because", "; ".join(res.review_reasons)))
    if pv:
        rows += [("Indicative rate", f"{pv['rate']:.2%}"), ("Monthly instalment", f"{pv['emi']:,.2f}")]
    rows += [("Officer", f"{user.display_name} ({user.username})"),
             ("Policy / model", f"v{c.policy_version} / {c.model_version}")]
    extra = []
    if reports.HAVE_PDF:
        try:
            reasons_json = [{"label": r.label, "contribution": r.contribution, "detail": r.detail}
                            for r in explanation["reasons"]]
            extra.append(("Full decision record (PDF)", reports.decision_pdf(
                app_id=res.application_id, customer_ref=ref, officer=f"{user.display_name} ({user.username})",
                outcome=outcome, probability=result["probability"], interval=interval, routing=result["routing"],
                policy_version=c.policy_version, model_version=c.model_version, policy_pass=result["policy_pass"],
                breaches=result["breaches"], inputs={**app, **extras}, reasons=reasons_json, rationale=rationale,
                loan_econ=pv), f"{res.application_id}.pdf", "application/pdf"))
            if not pending:
                adverse = [f"{r.label}: {r.detail}" for r in dec.adverse_reasons(explanation["reasons"])]
                terms = (f"Amount {app['loan_amount']:,.0f}, term {app['loan_term_months']} months"
                         + (f", indicative rate {pv['rate']:.2%}" if pv else "")) if outcome != "Decline" else ""
                extra.append(("Customer letter (PDF)", reports.customer_letter_pdf(
                    outcome=outcome, customer_ref=ref, reasons=adverse, terms=terms, human_reviewed=True),
                    f"{res.application_id}_letter.pdf", "application/pdf"))
        except Exception:
            pass
    _result.push(title="Decision saved", pdf_title="Credit decision slip", number=res.application_id,
                 status=status, tone=tone, rows=rows, next_steps=steps, extra_files=extra,
                 file_stem=f"{res.application_id}_slip", signatures=("Credit officer", "Checked by"))


def _render_record(app_id, c, app, e, result, interval, explanation, user, outcome, rationale, ref) -> str:
    lines = [
        "# Credit decision record", "",
        f"- Application ID: **{app_id}**",
        f"- Case reference: {ref}",
        f"- Application received: {app.get('application_date') or e.get('application_date') or '(not recorded)'}",
        f"- Saved: {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC "
        f"({to_local(datetime.now(timezone.utc).isoformat())} Phnom Penh time)",
        f"- Officer: {user.display_name} ({user.username})",
        f"- Officer decision: **{outcome}**",
        f"- Model score: **{result['probability'] * 100:.1f}%** "
        f"(90% range {interval[0] * 100:.0f}-{interval[1] * 100:.0f}%), routing: {result['routing']}",
        f"- Policy version {c.policy_version}; cut-off {c.cutoff:.0%}; model {c.model_version}",
        f"- Hard policy: {'pass' if result['policy_pass'] else 'BREACH - ' + '; '.join(result['breaches'])}",
    ]
    if result["out_of_range"]:
        lines.append(f"- Outside model training range: {'; '.join(result['out_of_range'])}")
    lines += ["", "## Application", "", "| Field | Value |", "|---|---|"]
    lines += [f"| {k.replace('_', ' ')} | {v} |" for k, v in app.items()]
    lines += ["", "## Affordability", "",
              f"- Estimated instalment: ${e['estimated_emi']:,.0f} per month (8.5% p.a. assumed)",
              f"- Debt-to-income: {e['debt_to_income_ratio'] * 100:.1f}%",
              f"- Loan to annual income: {e['loan_amount'] / (e['total_income'] * 12):.2f}x",
              "", "## Reasons (Shapley attribution of the final score, log-odds)", ""]
    for r in explanation["reasons"]:
        lines.append(f"- **{r.label}** ({r.detail}): {r.contribution:+.2f}")
    lines += ["", "## Officer rationale", "", rationale or "(not recorded)", "", "---", "",
              "The score is decision support trained on this institution's own past decisions, not on "
              "repayment outcomes. It sees no bureau file, collateral or existing liabilities. The "
              "recorded officer decision governs."]
    return "\n".join(lines)
