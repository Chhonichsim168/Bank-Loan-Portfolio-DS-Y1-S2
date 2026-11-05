"""Employee review of customer submissions and explicit ownership assignment."""
from __future__ import annotations

from datetime import timedelta

import streamlit as st

from src import audit, customer_portal as portal, customer_search, ui
from views import request_documents
from views._customer_feedback import show_error
from src.data_pipeline import today_local, to_local
from views.portal import cash


def render():
    portal.require_role(*portal.STAFF)
    ui.page_header("Customer requests", "Review customer applications, record a decision and issue approved loans.",
                   eyebrow="Decisioning")
    from views import customer_payments
    with st.expander("Verify customer payments"):
        customer_payments.render_staff()
    if st.button("Refresh customer requests"):
        st.rerun()
    review_tab, link_tab = st.tabs(["Review & issue", "Accounts for existing loans"])
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
                        elif portal.four_eyes_required() and not isinstance(r.second_approver, str):
                            _second_approval(r)
                        else:
                            if isinstance(r.second_approver, str):
                                st.success(f"Four-eyes check passed: second approval by {r.second_approver} "
                                           f"on {to_local(r.second_approved_at)}.")
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
        _accounts_for_existing_loans()


def _second_approval(r):
    """Four-eyes rule: a different Risk Manager / Administrator confirms before money is issued."""
    from src import auth
    me = auth.current_user()
    st.warning(f"Four-eyes rule: approved by {r.reviewed_by}. A second employee (Risk Manager or Administrator, "
               "not the first reviewer) must approve before the loan can be issued.")
    if me.role not in portal.SECOND_APPROVER_ROLES:
        st.caption("Ask a Risk Manager or Administrator to open this request and give the second approval.")
        return
    if me.username == r.reviewed_by:
        st.caption("You gave the first approval, so another Risk Manager or Administrator must give the second one.")
        return
    with st.form(f"second_{r.request_id}"):
        note = st.text_area("Second-approval note", max_chars=1000,
                            placeholder="e.g. Checked income documents and repayment capacity.")
        ok = st.checkbox("I checked this request independently and agree with the approved terms.")
        go = st.form_submit_button("Give second approval", type="primary")
    if go:
        if not ok:
            st.error("Tick the box to confirm your independent check.")
            return
        try:
            portal.second_approve(r.request_id, note)
            st.rerun()
        except (ValueError, PermissionError, audit.AuditError) as exc:
            st.error(str(exc))


def _accounts_for_existing_loans():
    """Loans issued at the branch: Admin / Risk Manager opens the customer's account and links the loans.
    The customer only signs in with the email - they never type a loan ID."""
    from src import auth
    me = auth.current_user()
    st.subheader("Open a customer account for an existing loan")
    st.caption("For loans issued at the branch. Check the customer's identity first. The customer receives an "
               "email and only has to sign in - their loan, schedule and payment history are already there.")
    loans = portal.unlinked_loans()
    if me.role not in portal.ACCOUNT_CREATOR_ROLES:
        st.info("Only an Administrator or a Risk Manager can open customer accounts for existing loans.")
        return
    done = st.session_state.pop("_acct_created", None)
    if done:
        msg = (f"Account **{done['username']}** for {done['email']} "
               + ("created" if done["created"] else "already existed") + f" and linked to {', '.join(done['loans'])}.")
        st.success(msg)
        if done.get("temp_password"):
            st.markdown("One-time password (shown only now; the customer chooses their own at the first sign-in):")
            st.code(done["temp_password"], language=None)
        st.caption("Invitation email: " + ("sent ✅" if not done.get("mail_problem") else done["mail_problem"]))
    if loans.empty:
        st.info("Every loan in the Loan book already belongs to a customer account.")
        return
    labels = {r.loan_id: f"{r.loan_id} · {r.customer_ref} · {cash(r.principal)}" for r in loans.itertuples()}
    with st.form("acct_for_loans", clear_on_submit=True):
        chosen = st.multiselect("Loan(s) of this customer", list(labels), format_func=labels.get)
        c1, c2 = st.columns(2)
        name = c1.text_input("Customer full name")
        email = c2.text_input("Customer email", placeholder="name@gmail.com",
                              help="The customer signs in with this email (password or Continue with Google).")
        c3, c4 = st.columns(2)
        phone = c3.text_input("Phone number")
        location = c4.text_input("Address")
        send = st.checkbox("Email the sign-in details to the customer", value=True)
        ok = st.checkbox("I checked the customer's ID card and that these loans are theirs.")
        go = st.form_submit_button("Create account and link loan(s)", type="primary")
    if go:
        if not ok:
            st.error("Confirm the identity check first.")
            return
        try:
            info = portal.create_account_for_loans(chosen, name, email, phone, location)
        except (ValueError, PermissionError, audit.AuditError) as exc:
            st.error(str(exc))
            return
        problem = portal.send_account_invitation(info, name) if send else "not sent (unticked)"
        st.session_state["_acct_created"] = {**info, "loans": chosen, "mail_problem": problem}
        st.rerun()

    with st.expander("Link a loan to a customer who already has an account"):
        accounts = portal.customer_accounts()
        if not accounts:
            st.caption("No customer accounts yet.")
            return
        with st.form("link_customer_loan"):
            names = {a["username"]: a["display_name"] for a in accounts}
            username = st.selectbox("Customer account", list(names), format_func=lambda x: f"{names[x]} ({x})")
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
