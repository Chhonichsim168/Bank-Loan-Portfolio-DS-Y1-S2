"""Policy and cut-offs — where a lending policy team tests a rule before it ships."""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src import decisioning as dec
from views._filters import filter_bar
from src import ui
from src.data_pipeline import MAX_CREDIT_SCORE, MAX_LATE_PAYMENTS_12M, MIN_CREDIT_SCORE, days_since, to_local
from src import policy_store
from src.security import to_safe_csv
from src.state import ctx, honest_probabilities, fingerprint_of
from src import auth, audit


def render() -> None:
    c = ctx()

    ui.page_header(
        "Policy and cut-offs",
        "Change a rule and see what it would have done to this book — volume blocked, "
        "good business caught with it, and which rule is doing the work.",
        eyebrow="Decisioning",
    )
    filter_bar(c)

    act = policy_store.active()
    _banner(act)

    tab_rules, tab_cutoff, tab_queue, tab_change = st.tabs(
        ["Underwriting rules", "Model cut-off", "Exceptions queue", "Change control"]
    )

    with tab_rules:
        _rules(c, act)
    with tab_cutoff:
        _cutoff(c, act)
    with tab_queue:
        _queue(c, act)
    with tab_change:
        _change_control(act)


def _k(name: str, act) -> str:
    """Widget keys carry the active version, so they reset to the new values after an approval."""
    return f"pol_{name}_v{act.version}"


def _banner(act) -> None:
    s = act.settings
    if act.version:
        days = int(days_since([act.effective_from]).iloc[0] or 0)
        who = (f"proposed by {act.proposed_by}, approved by {act.approved_by}, effective "
               f"{to_local(act.effective_from)} Phnom Penh time ({days} day{'s' if days != 1 else ''} in force)")
    else:
        who = "built-in defaults - no change has been approved yet"
    ui.note(
        f"<b>Policy version {act.version}</b> is in force for every user - {who}. "
        f"Cut-off {s.cutoff:.0%}; DTI at most {s.max_dti:.0%}; loan at most {s.max_lti:.2f}x annual income; "
        f"credit score at least {s.min_credit_score}; at most {s.max_late_payments} late payment(s); "
        f"loans above ${s.officer_authority_limit:,.0f} need a second approver. "
        "The sliders below are a <b>draft</b>: they change nothing until proposed and approved on the "
        "Change control tab.", title="Active policy", tone="info")


# (field, label, min %, max %, help) - stored as fractions, edited as percentages
PCT_FIELDS = [
    ("max_total_dti", "Max total debt service (new + existing debts) %", 5.0, 150.0, "Instalment plus existing monthly debts over income."),
    ("base_rate", "Base interest rate % p.a.", 0.0, 60.0, "Rate for the best band."),
    ("spread_review", "Extra rate: Review band %", 0.0, 30.0, ""),
    ("spread_refer", "Extra rate: Refer band %", 0.0, 30.0, ""),
    ("lgd_unsecured", "Loss given default, unsecured %", 0.0, 100.0, "Share of the loan lost if an unsecured borrower defaults."),
    ("collateral_haircut", "Collateral haircut %", 0.0, 100.0, "Collateral counts at (100% - haircut) of its value."),
    ("pd_fast_track", "Assumed default probability: Fast-track %", 0.0, 100.0, "Your assumption, not model output."),
    ("pd_review", "Assumed default probability: Review %", 0.0, 100.0, ""),
    ("pd_refer", "Assumed default probability: Refer %", 0.0, 100.0, ""),
    ("pd_decline", "Assumed default probability: Decline %", 0.0, 100.0, ""),
    ("max_npl_ratio", "Alert: NPL ratio above %", 0.1, 100.0, "Raises an alert on the Loan book page."),
    ("max_area_share", "Alert: one area above % of the book", 1.0, 100.0, ""),
    ("max_single_share", "Alert: one loan above % of the book", 0.1, 100.0, ""),
]


def _assumptions(s0, act) -> None:
    with st.expander("Pricing, loss assumptions and portfolio limits (draft)", expanded=False):
        st.caption("Used for the suggested price and expected loss on Score an application, and for the alerts and "
                   "provision estimate on the Loan book. Replace the starting values with your own experience; "
                   "the Loan book shows the observed default rate next to each assumption once loans have seasoned.")
        cols = st.columns(3, gap="medium")
        for i, (field, label, lo, hi, helptext) in enumerate(PCT_FIELDS):
            with cols[i % 3]:
                st.number_input(label, lo, hi, value=round(getattr(s0, field) * 100, 2), step=0.5,
                                key=_k(field, act), help=helptext or None)


def _draft(act) -> policy_store.Settings:
    """The settings currently dialled in on the page (not yet in force)."""
    s = act.settings
    g = st.session_state.get
    extra = {f: float(g(_k(f, act), round(getattr(s, f) * 100, 2))) / 100 for f, *_ in PCT_FIELDS}
    return policy_store.Settings(
        max_dti=g(_k("dti", act), round(s.max_dti * 100)) / 100,
        max_lti=float(g(_k("lti", act), s.max_lti)),
        require_credit_history=bool(g(_k("credit", act), s.require_credit_history)),
        exclude_unemployed=bool(g(_k("employed", act), s.exclude_unemployed)),
        min_credit_score=int(g(_k("score", act), s.min_credit_score)),
        max_late_payments=int(g(_k("late", act), s.max_late_payments)),
        cutoff=float(g(_k("cutoff", act), s.cutoff)),
        officer_authority_limit=float(g(_k("authority", act), s.officer_authority_limit)),
        **extra,
    )


# =========================================================================================
def _monthly_impact(tested: pd.DataFrame) -> None:
    """How the draft rules would have hit each month of applications (period filter applies)."""
    if "application_month" not in tested.columns or tested["application_month"].nunique() < 2:
        return
    m = tested.groupby("application_month").agg(
        applications=("policy_pass", "size"), blocked=("policy_pass", lambda x: (~x).sum())).reset_index()
    gb = tested[~tested["policy_pass"]].groupby("application_month")["approved"].sum()
    m["good_blocked"] = m["application_month"].map(gb).fillna(0).astype(int)
    m["blocked_share"] = m["blocked"] / m["applications"]
    ui.section("Month by month",
               "Share of each month's applications the draft rules would block. A rising line means the "
               "applicant mix is drifting toward the rule limits; use the Period filter to focus on recent months.")
    fig = go.Figure()
    fig.add_bar(x=m["application_month"], y=m["good_blocked"], name="Approved by the bank but blocked",
                marker_color=ui.MED, opacity=0.7, yaxis="y2",
                hovertemplate="%{x}<br>%{y:,} good applications blocked<extra></extra>")
    fig.add_scatter(x=m["application_month"], y=m["blocked_share"], name="Blocked share", mode="lines+markers",
                    line=dict(color=ui.HIGH, width=2.4), hovertemplate="%{x}<br>%{y:.1%} blocked<extra></extra>")
    fig.update_layout(yaxis=dict(title="Blocked share", tickformat=".0%", rangemode="tozero"),
                      yaxis2=dict(title="Good applications blocked", overlaying="y", side="right",
                                  showgrid=False, rangemode="tozero", tickmode="auto", tickformat="d"),
                      xaxis=dict(type="category", tickangle=-45), legend=dict(orientation="h", y=1.15, x=0))
    ui.chart(fig, height=280)


def version_timeline(hist: list[dict]) -> pd.DataFrame:
    """Every APPROVED policy version with the dates it was in force (local time)."""
    h = pd.DataFrame(hist)
    if h.empty or not (h["kind"] == "approve").any():
        return pd.DataFrame(columns=["Version", "In force from", "In force until", "Days in force",
                                     "Approved by", "Reason"])
    props = h[h["kind"] == "propose"].set_index("id")
    ap = h[h["kind"] == "approve"].sort_values("id").reset_index(drop=True)
    starts = pd.to_datetime(ap["ts"], utc=True)
    ends = list(starts.iloc[1:]) + [pd.Timestamp.now(tz="UTC")]
    out = pd.DataFrame({
        "Version": ap["ref_id"].astype(int),
        "In force from": to_local(ap["ts"]),
        "In force until": list(to_local(ap["ts"].iloc[1:])) + ["(current)"],
        "Days in force": [max(0, (e - s).days) for s, e in zip(starts, ends)],
        "Approved by": ap["username"],
        "Reason": [props["reason"].get(r, "") for r in ap["ref_id"]],
    })
    return out.iloc[::-1].reset_index(drop=True)


def _rules(c, act) -> None:
    s0 = act.settings
    ui.section("Hard rules (draft)", "Applied before any model score. Dial in a draft here and see its "
                                     "impact; it only takes effect once approved (Change control tab).")

    a, b, d, e = st.columns([1, 1, 1, 1], gap="medium")
    with a:
        st.slider("Maximum debt-to-income", 20, 80, value=round(s0.max_dti * 100), key=_k("dti", act), step=1, format="%d%%")
    with b:
        st.slider("Maximum loan to annual income", 1.5, 8.0, value=float(s0.max_lti), key=_k("lti", act),
                  step=0.25, format="%.2fx")
    with d:
        st.slider("Minimum credit score", MIN_CREDIT_SCORE, MAX_CREDIT_SCORE, value=int(s0.min_credit_score),
                  key=_k("score", act),
                  step=10, help=f"Applicants below this score are blocked. "
                                f"{MIN_CREDIT_SCORE} switches the rule off.")
    with e:
        st.slider("Maximum late payments (12 months)", 0, MAX_LATE_PAYMENTS_12M,
                  value=int(s0.max_late_payments), key=_k("late", act), step=1,
                  help=f"Applicants with more late payments than this are blocked. "
                       f"{MAX_LATE_PAYMENTS_12M} switches the rule off.")

    t1, t2, t3, _ = st.columns([1, 1, 1, 1], gap="medium")
    with t1:
        st.toggle("Require credit history", value=s0.require_credit_history, key=_k("credit", act))
    with t2:
        st.toggle("Require employment", value=s0.exclude_unemployed, key=_k("employed", act))
    with t3:
        st.number_input("Officer authority limit ($)", 0, 5_000_000, value=int(s0.officer_authority_limit),
                        step=10_000, key=_k("authority", act),
                        help="Approving a loan above this needs a second approver.")

    _assumptions(s0, act)
    policy = _draft(act).policy()

    impact = dec.policy_impact(c.view, policy)
    if impact["blocked_n"] == 0:
        ui.note("This policy blocks nothing in the current selection. Either the rules are "
                "looser than the book, or the filters have already excluded the breaches.",
                title="No impact", tone="info")

    cols = st.columns(4, gap="small")
    with cols[0]:
        ui.kpi("Applications blocked", f"{impact['blocked_n']:,}",
               delta=ui.pct(impact["blocked_share"]),
               delta_dir="flat", foot="of the current selection")
    with cols[1]:
        ui.kpi("Volume blocked", ui.money(impact["blocked_volume"]),
               foot="requested principal held back")
    with cols[2]:
        ui.kpi("Approval rate of what passes", ui.pct(impact["pass_approval_rate"]),
               delta=ui.pp(impact["pass_approval_rate"] - float(c.view["approved"].mean())),
               delta_dir="up", foot="against the unfiltered selection")
    with cols[3]:
        ui.kpi("Good business blocked", f"{impact['approved_but_blocked']:,}",
               delta_dir="down",
               foot="applications the bank did approve, that this rule would stop")

    _monthly_impact(impact["tested"])

    st.markdown("")
    left, right = st.columns([1.3, 1], gap="large")

    with left:
        ui.section("Which rule is doing the work")
        breaches = impact["top_breach"]
        if len(breaches):
            fig = go.Figure(go.Bar(
                y=list(breaches.index), x=list(breaches.values), orientation="h",
                marker_color=ui.BRAND, marker_line_width=0, opacity=0.88,
                text=[f"{v:,}" for v in breaches.values], textposition="outside",
                textfont=dict(size=11.5, color=ui.INK),
                hovertemplate="%{y}<br>%{x:,} applications<extra></extra>",
            ))
            fig.update_layout(
                xaxis=dict(title="Applications caught",
                           range=[0, breaches.max() * 1.22]),
                yaxis=dict(title="", autorange="reversed"), bargap=0.4,
            )
            ui.chart(fig, height=max(200, 56 * len(breaches)))
            ui.note(
                f"<b>{breaches.index[0]}</b> catches the most applications "
                f"({breaches.iloc[0]:,}). A rule that dominates the others this heavily is "
                "effectively the policy — worth confirming that is intended rather than an "
                "artefact of where the threshold happens to sit."
            )

    with right:
        ui.section("Current rule set")
        rules_html = "".join(
            f'<div style="padding:0.42rem 0;border-bottom:1px solid {ui.BORDER};'
            f'font-size:0.875rem;">{r}</div>'
            for r in policy.describe()
        )
        st.markdown(f'<div class="cd-panel">{rules_html}</div>', unsafe_allow_html=True)

        ui.note(
            f"Applications that pass approve at <b>{ui.pct(impact['pass_approval_rate'])}</b>; "
            f"those blocked approved at <b>{ui.pct(impact['blocked_approval_rate'])}</b> "
            "historically. The wider that gap, the better the rule set is separating credit "
            "the bank wants from credit it does not.",
            title="Is this policy discriminating?",
        )


# =========================================================================================
def _cutoff(c, act) -> None:
    ui.section(
        "Where to set the model cut-off",
        "Scored out-of-fold: every application is scored by a model that never saw it in "
        "training, so these trade-offs are the ones you would actually get in production.",
    )

    proba = honest_probabilities(c.book, fingerprint_of(c.book))
    y = c.book["approved"].values
    sweep = dec.threshold_sweep(y, proba)

    cutoff = st.slider(
        "Approval cut-off (draft)", 0.05, 0.95, value=float(act.settings.cutoff), key=_k("cutoff", act), step=0.01,
        help="Applications scoring at or above this go forward; below it they are declined "
             "or referred.",
    )
    cm = dec.confusion_at(y, proba, cutoff)
    n = len(y)

    cols = st.columns(4, gap="small")
    with cols[0]:
        ui.kpi("Applications approved", f"{(cm['tp'] + cm['fp']) / n * 100:.1f}%",
               foot=f"{cm['tp'] + cm['fp']:,} of {n:,}")
    with cols[1]:
        prec = cm["tp"] / max(cm["tp"] + cm["fp"], 1)
        ui.kpi("Of those, historically good", ui.pct(prec),
               foot="precision at this cut-off")
    with cols[2]:
        ui.kpi("Bad business let through", f"{cm['fp']:,}",
               delta_dir="down",
               foot="declined historically, approved by the model")
    with cols[3]:
        ui.kpi("Good business turned away", f"{cm['fn']:,}",
               delta_dir="down",
               foot="approved historically, declined by the model")

    st.markdown("")
    fig = go.Figure()
    fig.add_scatter(x=sweep["threshold"], y=sweep["false_approvals"], mode="lines",
                    name="Bad business let through",
                    line=dict(color=ui.HIGH, width=2.4),
                    hovertemplate="Cut-off %{x:.2f}<br>%{y:,} cases<extra></extra>")
    fig.add_scatter(x=sweep["threshold"], y=sweep["missed_good"], mode="lines",
                    name="Good business turned away",
                    line=dict(color=ui.BRAND, width=2.4),
                    hovertemplate="Cut-off %{x:.2f}<br>%{y:,} cases<extra></extra>")
    fig.add_vline(x=cutoff, line_color=ui.INK, line_width=1.4, line_dash="dot",
                  annotation_text=f"cut-off {cutoff:.2f}", annotation_position="top",
                  annotation_font=dict(size=11, color=ui.INK))
    fig.update_layout(
        xaxis=dict(title="Approval cut-off"),
        yaxis=dict(title="Applications"),
        legend=dict(orientation="h", y=1.1, x=0),
    )
    ui.chart(fig, height=330)

    crossing = sweep.iloc[(sweep["false_approvals"] - sweep["missed_good"]).abs().argmin()]
    ui.note(
        f"The two costs cross at a cut-off of <b>{crossing['threshold']:.2f}</b>, where each "
        f"kind of mistake happens about {int(crossing['false_approvals']):,} times. That "
        "crossing point is only the right answer if both mistakes cost the same, and they "
        "rarely do — a bad loan usually costs a multiple of a lost one. Move the cut-off up "
        "until the ratio of the two lines matches your actual loss-to-margin ratio.",
        title="Reading the trade-off",
    )

    with st.expander("Full cut-off table"):
        tbl = sweep[["threshold", "approved_share", "precision", "recall", "accuracy",
                     "false_approvals", "missed_good"]].copy()
        tbl.columns = ["Cut-off", "Share approved", "Precision", "Recall", "Accuracy",
                       "Bad let through", "Good turned away"]
        ui.table(
            tbl.style.format({
                "Cut-off": "{:.2f}", "Share approved": "{:.1%}", "Precision": "{:.1%}",
                "Recall": "{:.1%}", "Accuracy": "{:.1%}",
                "Bad let through": "{:,}", "Good turned away": "{:,}",
            }), hide_index=True, height=340,
        )


# =========================================================================================
def _queue(c, act) -> None:
    policy = act.settings.policy()

    ui.section("Exceptions queue",
               "Every application in the current selection that breaches policy, ordered by "
               "exposure at risk.")

    flagged = dec.exceptions(c.view, policy, limit=500)
    if flagged.empty:
        ui.note("Nothing in this selection breaches policy.", title="Queue is clear")
        return

    cols = st.columns(3, gap="small")
    with cols[0]:
        ui.kpi("In the queue", f"{len(flagged):,}")
    with cols[1]:
        ui.kpi("Exposure flagged", ui.money(float(flagged["loan_amount"].sum())))
    with cols[2]:
        multi = int((flagged["breach_count"] > 1).sum())
        ui.kpi("Breaching more than one rule", f"{multi:,}",
               foot="these should be looked at first")

    st.markdown("")
    display = flagged.copy()
    display = pd.DataFrame({
        "Loan": display["loan_amount"],
        "Monthly income": display["total_income"],
        "DTI": display["debt_to_income_ratio"] * 100,
        "Loan / annual income": display["loan_to_annual_income"],
        "Credit score": display["credit_score"],
        "Late payments (12m)": display["late_payments_12m"],
        "Credit history": np.where(display["credit_history"] == 1, "On file", "None"),
        "Employment": display["employment_status"].str.replace("_", "-"),
        "Area": display["property_area"].str.title(),
        "Risk": display["risk_level"],
        "Breaches": display["breach_count"],
        "Why it is flagged": display["breach_reason"],
        "Historic outcome": np.where(display["approved"] == 1, "Approved", "Declined"),
    })

    ui.table(
        display.style.format({
            "Loan": "${:,.0f}", "Monthly income": "${:,.0f}",
            "DTI": "{:.0f}%", "Loan / annual income": "{:.2f}x",
        }), hide_index=True, height=420,
    )

    st.download_button(
        "Download queue (CSV)",
        to_safe_csv(display),
        file_name="credit_desk_exceptions.csv", mime="text/csv", type="primary",
    )


# =========================================================================================
def _change_control(act) -> None:
    user = auth.current_user()
    draft = _draft(act)
    ui.section("Propose a change",
               "A proposal needs a written reason and a second person - a different Risk Manager or "
               "Administrator - to approve it before it applies to anyone.")

    labels = {"max_dti": "Max DTI", "max_lti": "Max loan / annual income", "min_credit_score": "Min credit score",
              "max_late_payments": "Max late payments", "require_credit_history": "Require credit history",
              "exclude_unemployed": "Require employment", "cutoff": "Model cut-off",
              "officer_authority_limit": "Officer authority limit"}
    labels.update({f: lbl for f, lbl, *_ in PCT_FIELDS})
    diff = []
    for f in labels:
        a_, b_ = getattr(act.settings, f), getattr(draft, f)
        if abs(float(a_) - float(b_)) > 1e-9 if not isinstance(a_, bool) else a_ != b_:
            diff.append((labels[f], a_, b_))
    if diff:
        ui.table(pd.DataFrame(diff, columns=["Setting", "In force", "Draft"]).astype(str), hide_index=True)
    else:
        st.caption("The draft is identical to the policy in force.")
    reason = st.text_area("Reason for the change (required, kept in the audit record)", key="pol_reason", height=90)
    if st.button("Submit proposal", type="primary", disabled=not diff):
        try:
            pid = policy_store.propose(draft, user.username, user.role, reason)
            from views import _result
            _result.push(title="Policy change submitted", pdf_title="Policy change proposal", number=f"POL-{pid}",
                         status="Submitted - waiting for a second person to approve", tone="warn",
                         rows=[("Proposal", f"#{pid}"), ("Proposed by", f"{user.display_name} ({user.username})"),
                               ("Reason", reason.strip())] + [(lbl, f"{a_} -> {b_}") for lbl, a_, b_ in diff],
                         next_steps=["Another Risk Manager or Administrator approves or rejects it under "
                                     "Change control > Waiting for approval.",
                                     "The new rules apply to every officer the moment it is approved."],
                         file_stem=f"policy_proposal_{pid}", signatures=("Proposed by", "Approved by"))
            st.success(f"Proposal #{pid} submitted. It applies once a second person approves it.")
            st.rerun()
        except (ValueError, audit.AuditError) as exc:
            st.error(str(exc))

    ui.section("Waiting for approval")
    pend = policy_store.pending()
    if not pend:
        st.caption("No proposals are waiting.")
    for p in pend:
        s = p["settings"]
        with st.container(border=True):
            st.markdown(f"**Proposal #{p['id']}** by {p['username']} at {p['ts'][:16]} UTC - {p['reason']}")
            st.caption(f"DTI {s.max_dti:.0%} | LTI {s.max_lti:.2f}x | score >= {s.min_credit_score} | "
                       f"late <= {s.max_late_payments} | cut-off {s.cutoff:.0%} | "
                       f"authority ${s.officer_authority_limit:,.0f}")
            note = st.text_input("Comment", key=f"pol_note_{p['id']}")
            a, b, _ = st.columns([1, 1, 4])
            for col, ok, label in ((a, True, "Approve"), (b, False, "Reject")):
                with col:
                    if st.button(label, key=f"pol_{label}_{p['id']}"):
                        try:
                            policy_store.decide(p["id"], ok, user.username, user.role, note)
                            from views import _result
                            _result.push(
                                title="Policy change " + ("approved" if ok else "rejected"),
                                pdf_title="Policy change decision", number=f"POL-{p['id']}",
                                status=("Approved - the new rules are now in force" if ok else
                                        "Rejected - the current rules stay in force"),
                                tone="good" if ok else "stop",
                                rows=[("Proposal", f"#{p['id']}"), ("Proposed by", p["username"]),
                                      ("Reason given", p["reason"]),
                                      ("Decided by", f"{user.display_name} ({user.username})"),
                                      ("Comment", note or "-"),
                                      ("Max DTI / LTI", f"{s.max_dti:.0%} / {s.max_lti:.2f}x"),
                                      ("Min credit score / max late", f"{s.min_credit_score} / {s.max_late_payments}"),
                                      ("Cut-off / officer authority", f"{s.cutoff:.0%} / ${s.officer_authority_limit:,.0f}")],
                                next_steps=(["Every new score uses these rules from now on.",
                                             "The Version timeline below shows when each version was in force."]
                                            if ok else []),
                                file_stem=f"policy_decision_{p['id']}", signatures=("Proposed by", "Decided by"))
                            st.rerun()
                        except (ValueError, PermissionError, audit.AuditError) as exc:
                            st.error(str(exc))

    hist = policy_store.history(500)
    ui.section("Version timeline", "Which rules were in force on which dates - so any past decision can be "
                                   "judged against the policy of its day.")
    tl = version_timeline(hist)
    if tl.empty:
        st.caption("No version has been approved yet; the built-in defaults are in force.")
    else:
        ui.table(tl, hide_index=True)
    with st.expander("Policy history"):
        if hist:
            h = pd.DataFrame(hist)[["id", "ts", "username", "kind", "ref_id", "reason"]]
            h.insert(2, "local time", to_local(h["ts"]))
            ui.table(h, hide_index=True, height=300)
