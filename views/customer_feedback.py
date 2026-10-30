"""Visible, dismissible success confirmations and required-profile progress."""
import uuid
import streamlit as st
from src.customer_i18n import t


def confirm_action(title, detail=""):
    st.session_state["_customer_confirmation"] = {"id":uuid.uuid4().hex,"title":title,"detail":detail}


def show_confirmation():
    notice = st.session_state.get("_customer_confirmation")
    if not notice:
        return
    if st.session_state.get("_customer_confirmation_toast") != notice["id"]:
        st.toast(t(notice["title"]),icon="✅")
        st.session_state["_customer_confirmation_toast"] = notice["id"]
    with st.container(border=True):
        st.success(t(notice["title"]),icon="✅")
        if notice["detail"]:
            st.text(t(notice["detail"]))
        if st.button(t("Dismiss confirmation"),key="dismiss_customer_confirmation"):
            st.session_state.pop("_customer_confirmation",None)
            st.rerun()


def profile_completion(profile, compact=False):
    fields = [("Full name",profile.get("full_name")),("Phone number",profile.get("phone")),
              ("Location / address",profile.get("location"))]
    complete = sum(bool(str(value or "").strip()) for _,value in fields)
    missing = [t(label) for label,value in fields if not str(value or "").strip()]
    with st.container(border=True):
        st.subheader(t("Profile completion"))
        st.progress(complete/len(fields),text=f"{complete}/{len(fields)} · {complete/len(fields):.0%}")
        if missing:
            st.caption(t("Still needed") + ": " + ", ".join(missing))
            if compact and st.button(t("Complete my profile"),key="dashboard_complete_profile"):
                page=st.session_state.get("_customer_profile_page")
                if page is not None:
                    st.switch_page(page)
        else:
            st.caption(t("All required profile details are complete."))

