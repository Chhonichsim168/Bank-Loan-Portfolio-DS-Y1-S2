"""Complete application details, scoped to the current customer."""
import streamlit as st
from src import customer_portal as portal, ui
from src.customer_i18n import t
from src.data_pipeline import to_local
from src.deps import MissingLibrary
from views import request_documents


def render():
    portal.require_role("customer")
    ui.page_header(t("Request details"),'',eyebrow=t("Credit Desk · Customer"))
    from views.customer_feedback import show_confirmation
    show_confirmation()
    requests = portal.requests()
    if requests.empty:
        from views.customer_help import empty_state
        empty_state("requests")
        return
    rows = {row["request_id"]:row for row in requests.to_dict("records")}
    preferred = st.session_state.pop("_customer_detail_request",None)
    if preferred in rows:
        st.session_state["request_details_choice"] = preferred
    rid = st.selectbox(t("Request reference"),list(rows),format_func=lambda key: f"{key} · {t(rows[key]['status'])}",key="request_details_choice")
    row = rows[rid]
    status = row["status"]
    {"Approved":st.success,"Declined":st.error,"Cancelled":st.info}.get(status,st.info)(t(status))
    with st.container(border=True):
        st.subheader(t("Customer details"))
        for label,value in [("Full name",row["full_name"]),("Phone",row["phone"]),("Email",row["email"]),("Location",row["location"])]:
            st.text(f"{t(label)}: {value or t('Not provided')}")
    with st.container(border=True):
        for label,value in [("Request reference",rid),("Request date",to_local(row["submitted_at"])),
                ("Product",t(row["product"])),("Requested amount",f"${row['amount']:,.2f}"),
                ("Term",f"{int(row['term_months'])} {t('months')}"),("Purpose",row["purpose"])]:
            st.text(f"{t(label)}: {value}")
        if status in {"Approved","Declined"}:
            st.text(f"{t('Decision date')}: {to_local(row['decision_at'])}")
            st.text(f"{t('Decision notes')}: {row['explanation']}")
        if status == "Cancelled":
            st.text(f"{t('Cancelled')}: {to_local(row['cancelled_at'])}")
        if status == "Approved":
            st.text(f"{t('Approved')}: ${row['approved_amount']:,.2f} · {int(row['approved_term'])} {t('months')}")
            if row.get("loan_id"):
                loan,_,_,_ = portal.loan_details(row["loan_id"])
                rate_label = "Total interest rate" if loan.get("interest_method") == "flat_total" else "Annual interest rate"
                st.text(f"{t(rate_label)}: {loan['annual_rate']:.2%}")
                if st.button(t("View full loan details"),key="request_open_loan"):
                    st.session_state["_customer_detail_loan"] = row["loan_id"]
                    destination = st.session_state.get("_customer_loan_details_page")
                    if destination is not None:
                        st.switch_page(destination)
            else:
                st.info(t("Awaiting disbursement"))
    from views.request_terms import render as render_terms
    render_terms(row)
    try:
        st.download_button(t("Download request receipt (PDF)"),portal.request_receipt(rid),
            file_name=f"Loan_Request_{rid}.pdf",mime="application/pdf",key="request_details_receipt")
    except MissingLibrary:
        st.info(t("PDF request receipts require reportlab."))
    request_documents.render(rid,status)
    if st.button(t("Back to my requests"),key="request_details_back"):
        st.session_state["customer_home_section"] = "Loan requests"
        destination = st.session_state.get("_customer_home_page")
        if destination is not None:
            st.switch_page(destination)
