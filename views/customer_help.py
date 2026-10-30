"""Application guidance and FAQ for the customer portal."""
import streamlit as st
from src import customer_portal as portal, ui
from src.customer_i18n import t


def _open_requests():
    st.session_state["customer_home_section"] = "Loan requests"


def empty_state(kind):
    content = {
        "requests":("No loan requests yet", "Start by saving your profile, then review the cost estimate and submit a loan request. You can track its decision here."),
        "loans":("No loans to display", "An approved request appears here after the loan team issues it. If you already have a loan, ask support to check that it is linked to your account."),
        "payments":("No payments recorded yet", "Your confirmed payments and downloadable receipts will appear here. Check the repayment calendar for due dates. Report an actual payment using Report a payment."),
        "notifications":("You are all caught up", "Loan decisions, next-payment reminders and support replies will appear here when available."),
    }
    title, body = content[kind]
    with st.container(border=True):
        st.subheader(t(title))
        st.write(t(body))
        if kind in {"requests","loans"}:
            if st.button(t("Start a loan request"), key=f"empty_apply_{kind}",on_click=_open_requests):
                page = st.session_state.get("_customer_home_page")
                if page is not None:
                    st.switch_page(page)
        if st.button(t("Help / FAQ"),key=f"empty_help_{kind}"):
            page = st.session_state.get("_customer_help_page")
            if page is not None:
                st.switch_page(page)


def requirements(profile):
    with st.expander(t("Before you apply"),expanded=False):
        st.write(t("Required information"))
        checks = [("Full name",profile.get("full_name")),("Phone number",profile.get("phone")),
                  ("Location / address",profile.get("location"))]
        for label,value in checks:
            st.write(("✓ " if value else "○ ") + t(label))
        st.caption(t("Email and a profile photo are optional. Save your profile before submitting a request."))
        st.write(t("Choose the amount, term and loan product, explain the purpose, and review the estimate before confirming."))
        st.write(t("Supporting documents"))
        st.caption(t("The loan team may request identity, income or bank documents, depending on the application. They are not automatically required to submit this form."))
        st.caption(t("After submitting, open Request details to upload PDF, JPG or PNG documents up to 10 MB each while the request is pending review."))
        if not all(value for _,value in checks):
            if st.button(t("Complete my profile"),key="requirements_profile"):
                page=st.session_state.get("_customer_profile_page")
                if page is not None:
                    st.switch_page(page)


def render():
    portal.require_role("customer")
    ui.page_header(t("Help / FAQ"),t("Understand your loan, payments and application process."),eyebrow=t("Credit Desk · Customer"))
    requirements(portal.profile())
    items = [
      ("How do I request a loan?", "Complete your profile, choose the amount and term, enter a product and purpose, then preview and confirm. Submitting a request does not guarantee approval."),
      ("What do the request statuses mean?", "Pending review means the loan team has not decided yet. Approved means accepted, but the loan may still await disbursement. Declined means not accepted; read the decision notes. Cancelled means you withdrew the request."),
      ("How is interest calculated?", "Check the interest method on Loan details. Flat total interest is calculated once on the original principal for the full term. Annual reducing-balance interest is calculated monthly on the remaining principal. The application estimate is not your final approved rate."),
      ("Why is the final payment different?", "Payments are rounded to cents. The final installment is adjusted so the total principal and scheduled interest reconcile exactly."),
      ("What do Paid, Upcoming and Overdue mean?", "Paid means the installment is fully covered. Upcoming means an amount remains and its due date has not passed. Overdue means an amount remains after the due date. A partial payment leaves a remaining amount."),
      ("Does remaining principal include interest?", "No. Remaining principal is the borrowed amount still unpaid. Remaining scheduled repayment includes the unpaid interest in the schedule. Neither is a payoff quote."),
      ("How do I record a payment?", "Follow the verified payment instructions or contact support first. After paying, report the date, amount and transfer reference. Staff must confirm receipt before your balance changes. The website does not transfer money."),
      ("Where can I download my records?", "Request receipts are in request history and Request details. Payment receipts are under My loans & payments. Loan details includes statement and repayment schedule downloads. PDF exports are in English."),
      ("Can I cancel or edit a submitted request?", "You can cancel a pending request before staff review it. To change its amount, term or purpose, cancel it and submit a new request. Contact support about a request already reviewed."),
      ("How long are support chats kept?", "Chats expire 24 hours after the last message. A new message restarts that timer. Expired conversations are deleted when support data refreshes. Keep important confirmations outside the chat."),
      ("What if I forget my password?", "Use Forgot password on the sign-in screen with your saved recovery code. Codes are single-use. Generate a replacement in My account. If you have no code, ask an administrator for help."),
    ]
    for question,answer in items:
        with st.expander(t(question)):
            st.write(t(answer))
    if st.button(t("Contact support"),key="faq_support"):
        page=st.session_state.get("_customer_support_page")
        if page is not None:
            st.switch_page(page)
