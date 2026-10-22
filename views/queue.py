"""Decision queue - saved decisions, second approvals and the full case record."""

from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from src import audit, auth, reports, ui, workflow
from src.mode import single_operator
from src.data_pipeline import to_local, today_local
from src.security import esc, to_safe_csv


def render() -> None:
    user = auth.current_user()
    is_reviewer = user.role in workflow.REVIEW_ROLES

    ui.page_header(
        "Decision queue",
        "Every saved credit decision, with its status. Referrals, large loans and policy "
        "exceptions wait here for a second approver who is not the person who made them.",
        eyebrow="Decisioning",
    )

    df = workflow.add_timing(workflow.decisions(2000))
    if df.empty:
        ui.note("No decisions have been saved yet. Save one from Score an application.",
                title="Queue is empty")
        return

    mine = df[df["username"] == user.username]
    visible = df if is_reviewer else mine
    pending = df[df["status"] == "Pending second approval"]
    if not is_reviewer:
        awaiting_me = pending.iloc[0:0]
    elif single_operator():                      # one person runs the desk: they approve their own cases
        awaiting_me = pending
    else:
        awaiting_me = pending[pending["username"] != user.username]
    awaiting_me = awaiting_me.sort_values("days_waiting", ascending=False)      # oldest first

    cols = st.columns(5, gap="small")
    with cols[0]:
        ui.kpi("Saved decisions", f"{len(visible):,}", foot="all" if is_reviewer else "yours")
    with cols[1]:
        oldest = int(pending["days_waiting"].max()) if len(pending) else 0
        ui.kpi("Pending second approval", f"{len(pending):,}",
               foot=f"oldest waiting {oldest} day{'s' if oldest != 1 else ''}" if len(pending) else None)
    with cols[2]:
        ui.kpi("Waiting for you", f"{len(awaiting_me):,}", foot="reviewers only")
    with cols[3]:
        ui.kpi("Exposure pending", ui.money(float(pending['loan_amount'].sum())))
    with cols[4]:
        over = int(pending["over_sla"].sum())
        ui.kpi(f"Waiting > {workflow.REVIEW_SLA_DAYS} days", f"{over:,}",
               delta_dir="down" if over else "flat", foot="second-approval target")
    if len(pending) and pending["over_sla"].any():
        ui.note(f"<b>{int(pending['over_sla'].sum())}</b> case(s) have waited more than "
                f"{workflow.REVIEW_SLA_DAYS} days for a second approval. They are listed first.",
                title="Behind target", tone="warn")

    tab_wait, tab_all = st.tabs(["Needs a decision", "All cases"])
    with tab_wait:
        if not is_reviewer:
            ui.note("Second approvals are made by a Risk Manager or Administrator. You can follow "
                    "the status of your own cases in the All cases tab.", title="Reviewers only")
        elif awaiting_me.empty:
            ui.note("Nothing is waiting for you. Decisions you made yourself are excluded (four-eyes rule).",
                    title="All clear")
        else:
            _review_panel(awaiting_me, user)

    with tab_all:
        saved_day = pd.to_datetime(to_local(visible["created_at"], "%Y-%m-%d"), errors="coerce")
        lo, hi = saved_day.min().date(), max(saved_day.max().date(), today_local().date())
        rng = st.date_input("Saved between", value=(lo, hi), min_value=lo, max_value=hi,
                            key="q_range", format="DD/MM/YYYY")
        if isinstance(rng, (list, tuple)) and len(rng) == 2:
            keep = (saved_day >= pd.Timestamp(rng[0])) & (saved_day <= pd.Timestamp(rng[1]))
            visible = visible[keep.values]
        _volume(visible)
        view = visible[["application_id", "created_at", "received", "days_to_decide", "days_waiting", "username",
                        "customer_ref", "outcome", "loan_amount", "probability", "routing", "status",
                        "review_reasons", "reviewer"]].copy()
        view["created_at"] = to_local(view["created_at"])
        view["probability"] = view["probability"] * 100
        view.columns = ["Application", "Saved (Phnom Penh)", "Received", "Days to decide", "Waiting (days)",
                        "Officer", "Reference", "Decision", "Loan", "Score %",
                        "Routing", "Status", "Why second approval", "Reviewer"]
        ui.table(view.style.format({"Loan": "${:,.0f}", "Score %": "{:.1f}"}), hide_index=True, height=420)
        st.download_button("Download cases (CSV)", to_safe_csv(view), file_name="credit_desk_decisions.csv",
                           mime="text/csv")
        pick = st.selectbox("Open a case", [""] + visible["application_id"].tolist(), key="q_open")
        if pick:
            _case(visible[visible["application_id"] == pick].iloc[0])


def _volume(df: pd.DataFrame) -> None:
    """Decisions saved per week, by outcome."""
    if df.empty:
        return
    wk = pd.to_datetime(to_local(df["created_at"], "%Y-%m-%d"), errors="coerce").dt.to_period("W").dt.start_time
    if wk.nunique() < 2:
        return
    t = df.assign(week=wk.dt.strftime("%d/%m/%Y")).groupby(["week", "outcome"]).size().unstack(fill_value=0)
    t = t.loc[sorted(t.index, key=lambda d: pd.to_datetime(d, dayfirst=True))]
    st.caption("Decisions saved per week (week starting)")
    st.bar_chart(t, height=200)


def _case(row: pd.Series) -> None:
    ui.section(f"Case {row['application_id']}", f"{row['status']}")
    left, right = st.columns(2, gap="large")
    with left:
        st.markdown("**Application**")
        ui.table(pd.DataFrame(json.loads(row["inputs"]).items(), columns=["Field", "Value"]).astype(str),
                 hide_index=True)
        st.markdown(f"**Decision:** {esc(row['outcome'])} by {esc(row['username'])} at "
                    f"{esc(to_local(row['created_at']))} Phnom Penh time")
        if row.get("received"):
            dd = row.get("days_to_decide")
            st.markdown(f"**Received:** {esc(row['received'])}"
                        + (f" - decided {int(dd)} day(s) later" if dd is not None and not pd.isna(dd) else ""))
        if row.get("days_waiting") is not None and not pd.isna(row.get("days_waiting")):
            st.markdown(f"**Waiting for second approval:** {int(row['days_waiting'])} day(s)")
        st.markdown(f"**Score:** {row['probability'] * 100:.1f}% (routing {esc(row['routing'])}); "
                    f"policy v{row['policy_version']}; model {esc(row['model_version'])}")
        if not row["policy_pass"]:
            st.markdown(f"**Policy breaches:** {esc(row['breaches'])}")
        if row["review_reasons"]:
            st.markdown(f"**Second approval needed because:** {esc(row['review_reasons'])}")
    with right:
        st.markdown("**Reason codes**")
        rs = pd.DataFrame(json.loads(row["reasons"]))
        if not rs.empty:
            ui.table(rs, hide_index=True)
        st.markdown("**Officer rationale**")
        st.write(row["rationale"] or "(none)")
        if isinstance(row["reviewer"], str):
            st.markdown(f"**Reviewed by {esc(row['reviewer'])}:** {esc(row['review_verdict'])} - {esc(row['review_comment'])}")


def _review_panel(df: pd.DataFrame, user) -> None:
    pick = st.selectbox("Case to review", df["application_id"].tolist(), key="q_review_pick")
    row = df[df["application_id"] == pick].iloc[0]
    _case(row)
    comment = st.text_area("Your comment (required)", key=f"q_cmt_{pick}", height=90)
    a, b, c = st.columns(3)
    for col, verdict, label in ((a, "approved", "Approve"), (b, "rejected", "Reject"), (c, "returned", "Return to officer")):
        with col:
            if st.button(label, key=f"q_{verdict}_{pick}", type="primary" if verdict == "approved" else "secondary"):
                try:
                    workflow.review(pick, username=user.username, role=user.role, verdict=verdict, comment=comment)
                    _push_review_result(row, verdict, comment, user)
                    st.success(f"{pick}: {verdict}.")
                    st.rerun()
                except (ValueError, PermissionError, audit.AuditError) as exc:
                    st.error(str(exc))


def _push_review_result(row, verdict: str, comment: str, user) -> None:
    """The result window after Approve / Reject / Return to officer."""
    from views import _result
    officer = row["username"]
    tone, status, steps = {
        "approved": ("good", "Approved by the second approver - the decision is now final",
                     [f"The officer ({officer}) creates the loan in Loan book > Add a loan.",
                      "The customer letter can be printed from Score an application or the case record."]),
        "rejected": ("stop", "Rejected by the second approver - the application is declined",
                     [f"The officer ({officer}) informs the customer; the decline letter lists the reasons."]),
        "returned": ("warn", "Returned to the officer for changes",
                     [f"The officer ({officer}) sees the case as 'Returned to officer' with your comment.",
                      "They correct it in Score an application and save it again; it comes back to this queue."]),
    }[verdict]
    rows = [("Application", row["application_id"]), ("Customer / case", row["customer_ref"]),
            ("Loan amount", f"{float(row['loan_amount']):,.2f}"), ("Officer decision", f"{row['outcome']} by {officer}"),
            ("Model score", f"{float(row['probability']) * 100:.1f}% (routing {row['routing']})"),
            ("Why it needed review", row["review_reasons"] or "-"),
            ("Your verdict", {"approved": "Approve", "rejected": "Reject", "returned": "Return to officer"}[verdict]),
            ("Your comment", comment.strip()), ("Reviewed by", f"{user.display_name} ({user.username})")]
    _result.push(title="Review recorded", pdf_title="Second approval result", number=str(row["application_id"]),
                 status=status, tone=tone, rows=rows, next_steps=steps,
                 file_stem=f"{row['application_id']}_review", signatures=("Credit officer", "Second approver"))
