"""Show the saved customer estimate beside the employee-approved offer."""
import pandas as pd
import streamlit as st
from src import customer_portal as portal, loanbook
from src.customer_i18n import t
from src.data_pipeline import today_local


def render(request):
    rid = request["request_id"]
    estimate = portal.saved_request_estimate(rid)
    st.subheader(t("Estimated and approved terms"))
    left,right = st.columns(2)
    with left:
        with st.container(border=True):
            st.markdown("**" + t("Estimate reviewed by customer") + "**")
            if estimate is None:
                st.caption(t("No estimate was saved with this older request."))
            else:
                st.text(f"{t('Amount')}: ${request['amount']:,.2f}")
                st.text(f"{t('Term')}: {int(request['term_months'])} {t('months')}")
                st.text(f"{t('Total interest rate')}: {estimate['rate_percent']:.2f}% · {t('Total flat interest')}")
                for label,column in [("Total interest","total_interest"),("Total repayment","total_repayment"),
                                     ("Monthly payment","monthly_payment"),("Final payment","final_payment")]:
                    st.text(f"{t(label)}: ${estimate[column]:,.2f}")
    with right:
        with st.container(border=True):
            st.markdown("**" + t("Approved terms") + "**")
            if request["status"] != "Approved":
                st.caption(t("No approved offer yet.") if request["status"] == "Pending review" else t("No approved offer for this request."))
                return
            method = "reducing"
            linked = request.get("loan_id")
            if linked and pd.notna(linked):
                loans = loanbook.list_loans()
                match = loans[loans["loan_id"] == linked]
                loan = match.iloc[0].to_dict() if not match.empty else None
            else:
                loan = None
            if loan is None:
                loan = dict(principal=float(request["approved_amount"]),annual_rate=float(request["approved_rate"]),
                    term_months=int(request["approved_term"]),first_due_on=today_local().date().isoformat(),interest_method="reducing")
            method = loan.get("interest_method","reducing")
            schedule = loanbook.schedule(loan)
            rate_label = "Total interest rate" if method == "flat_total" else "Annual interest rate"
            st.text(f"{t('Amount')}: ${loan['principal']:,.2f}")
            st.text(f"{t('Term')}: {loan['term_months']} {t('months')}")
            st.text(f"{t(rate_label)}: {loan['annual_rate']:.2%}")
            st.caption(t("Total flat interest") if method == "flat_total" else t("Annual reducing-balance interest"))
            for label,value in [("Total interest",schedule["interest"].sum()),("Total repayment",schedule["installment"].sum()),
                                ("Monthly payment",schedule["installment"].iloc[0]),("Final payment",schedule["installment"].iloc[-1])]:
                st.text(f"{t(label)}: ${value:,.2f}")
            if not linked or pd.isna(linked):
                st.caption(t("Payment dates are assigned when the loan is issued."))
    if estimate is not None:
        changed = (abs(float(request["amount"])-float(loan["principal"]))>.005
            or int(request["term_months"])!=int(loan["term_months"])
            or abs(float(estimate["rate_percent"])-float(loan["annual_rate"])*100)>.000001
            or method!=estimate["interest_method"])
        if changed:
            st.warning(t("Approved terms differ from the estimate. Check the rate, calculation method, term and payments carefully."))
        else:
            st.success(t("Approved terms match the saved estimate."))
