"""Employee review of customer submissions and explicit ownership assignment."""
from __future__ import annotations

from datetime import timedelta

import streamlit as st

from src import audit, customer_portal as portal, customer_search, ui
from views import request_documents
from views._customer_feedback import show_error
from src.data_pipeline import today_local, to_local
from views.customer import cash


def render():
    portal.require_role(*portal.STAFF)
    ui.page_header("Customer requests", "Review customer applications, record a decision and issue approved loans.",
                   eyebrow="Decisioning")
    from views import customer_payments
    with st.expander("Verify customer payments"):
        customer_payments.render_staff()
    if st.button("Refresh customer requests"):
        st.rerun()
    review_tab, link_tab = st.tabs(["Review & issue", "Link an existing loan"])
    with review_tab:
        requests = portal.requests()
        if requests.empty:
            st.info("No customer requests yet. Customers create an account from the sign-in page and apply in their portal.")
        else:
            status = st.selectbox("Show requests", ["Pending review", "Approved", "Declined", "Cancelled", "All"])
            query = st.text_input("Search customer requests", placeholder="Customer, username, reference or purpose")
            rows = customer_search.filter_records(requests, query, ("full_name", "username", "request_id", "purpose"), status)
            if rows.empty:
                st.info("No requests match this status and search. Clear the search or choose All statuses.")
            else:
                ids = rows["request_id"].tolist()
                rid = st.selectbox("Request", ids, format_func=lambda x:
                                  f"{x} · {rows.loc[rows.request_id == x, 'full_name'].iloc[0]}")
                r = rows[rows["request_id"] == rid].iloc[0]
                st.write(f"Customer: {r.full_name} · Account: {r.username}")
                st.write(f"Location: {r.location}")
                st.write(f"Phone: {r.phone} · Email: {r.email or 'Not provided'}")
                st.write(f"Requested: {to_local(r.submitted_at)} · {cash(r.amount)} · {r.product} · {r.term_months} months")
                st.write(f"Purpose: {r.purpose}")
                st.write(f"Status: {r.status}")
                from views.request_terms import render as render_terms
                render_terms(r)
                request_documents.render(rid, r.status, staff=True)
                if r.status == "Pending review":
                    with st.form(f"review_{rid}"):
                        decision = st.radio("Decision", ["Approved", "Declined"], horizontal=True)
                        c = st.columns(3)
                        amount = c[0].number_input("Approved amount ($)", min_value=.01,
                                                   max_value=float(r.amount), value=float(r.amount))
                        rate = c[1].number_input("Annual interest (%)", min_value=0.0, max_value=100.0, value=12.0)
                        term = c[2].number_input("Approved term (months)", min_value=1, max_value=360,
                                                 value=int(r.term_months))
                        explanation = st.text_area("Explanation for the customer", max_chars=2000)
                        st.caption("Approved terms apply only to approval. Customers can read this explanation.")
                        submit = st.form_submit_button("Save employee decision", type="primary")
                    if submit:
                        try:
                            portal.review(rid, decision, explanation, amount, rate / 100, term)
                            st.rerun()
                        except (ValueError, PermissionError, OSError, audit.AuditError) as exc:
                            show_error(exc, "save the decision")
                elif r.status == "Cancelled":
                    st.info(f"Cancelled by the customer on {to_local(r.cancelled_at)}. This request cannot be reviewed or issued.")
                else:
                    st.write(f"Decision: {to_local(r.decision_at)} · Reviewed by: {r.reviewed_by}")
                    st.write(f"Explanation: {r.explanation}")
                    if r.status == "Approved":
                        st.write(f"Approved terms: {cash(r.approved_amount)} · {r.approved_rate:.2%} · "
                                 f"{r.approved_term:.0f} months")
                        if r.loan_id:
                            st.success(f"Loan issued: {r.loan_id}. Manage payments in Loan book.")
                        else:
                            with st.form(f"issue_{rid}"):
                                today = today_local().date()
                                issued = st.date_input("Money issued on", value=today, max_value=today)
                                first_due = st.date_input("First payment due", value=today + timedelta(days=30))
                                confirmed = st.checkbox("I confirm the money has been issued to this customer.")
                                issue = st.form_submit_button("Record issued loan", type="primary")
                            if issue:
                                if not confirmed:
                                    st.error("Confirm that the funds have been issued first.")
                                else:
                                    try:
                                        portal.issue_loan(rid, issued, first_due)
                                        st.rerun()
                                    except (ValueError, audit.AuditError) as exc:
                                        st.error(str(exc))
    with link_tab:
        st.subheader("Connect an existing record to a customer")
        st.caption("Check the customer's identity and loan record before linking. "
                   "The customer will be able to see this loan and its payment history.")
        accounts, loans = portal.customer_accounts(), portal.unlinked_loans()
        if not accounts or loans.empty:
            st.info("You need a customer account and an unlinked loan to use this section.")
        else:
            with st.form("link_customer_loan"):
                names = {a["username"]: a["display_name"] for a in accounts}
                username = st.selectbox("Customer account", list(names), format_func=lambda x: f"{names[x]} ({x})")
                labels = {r.loan_id: f"{r.loan_id} · {r.customer_ref} · {cash(r.principal)}" for r in loans.itertuples()}
                lid = st.selectbox("Existing loan", list(labels), format_func=labels.get)
                confirmed = st.checkbox("I verified this loan belongs to this customer.")
                link = st.form_submit_button("Link loan to customer")
            if link:
                if not confirmed:
                    st.error("Verify the owner before linking the loan.")
                else:
                    try:
                        portal.link_existing(lid, username)
                        st.rerun()
                    except (ValueError, audit.AuditError) as exc:
                        st.error(str(exc))
