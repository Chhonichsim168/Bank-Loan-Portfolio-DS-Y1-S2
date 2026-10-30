"""Consistent top-left Undo control on signed-in pages."""
import streamlit as st
from src import customer_undo, audit
from src.customer_i18n import t
from views.customer_feedback import confirm_action


def render():
    action=customer_undo.latest()
    st.markdown("""<style>
      .st-key-global_undo {position:fixed;top:22px;left:140px;width:102px;z-index:2147483000;}
      [data-testid="stApp"]:has([data-testid="stSidebar"][aria-expanded="true"]) .st-key-global_undo {left:286px;}
      .st-key-global_undo button {width:102px!important;min-height:44px;border-radius:9px!important;
        background:#FFF;border:1px solid #CBD5E1;color:#07453F;box-shadow:0 2px 8px #0F172A12;font-weight:600;}
      @media(max-width:640px){.st-key-global_undo{top:12px;left:140px;}
        [data-testid="stApp"]:has([data-testid="stSidebar"][aria-expanded="true"]) .st-key-global_undo{display:none;}}
    </style>""",unsafe_allow_html=True)
    help_text=t("Nothing to undo yet.") if action is None else t("Undo")+": "+t(action["label"])
    if st.button("↶ "+t("Undo"),key="global_undo",help=help_text,disabled=action is None):
        try:
            result=customer_undo.undo(action["id"])
            if result["ok"]:
                if result["kind"] in {"draft","request_submit"}:
                    st.session_state["_application_reset"]=True
                    st.session_state.pop("_customer_request_preview",None)
                if result["kind"]=="profile":
                    for key in ["i18n_views_customer_py_450","i18n_views_customer_py_451","i18n_views_customer_py_452",
                                "i18n_views_customer_py_453","_customer_photo_upload","_customer_photo_draft"]:
                        st.session_state.pop(key,None)
                st.session_state.pop("_customer_profile_saved",None)
                confirm_action("Action undone",t(result["label"]))
                st.session_state["_undo_toast"]=t("Action undone")+": "+t(result["label"])
            else:
                st.session_state["_undo_toast"]=t("This action can no longer be undone because its record changed.")
            st.rerun()
        except (ValueError,PermissionError,OSError,audit.AuditError) as exc:
            st.toast(t(str(exc)) if isinstance(exc,(ValueError,PermissionError)) else t("Undo could not be saved. Please try again."),icon="⚠️")
    notice=st.session_state.pop("_undo_toast",None)
    if notice:
        st.toast(notice)
