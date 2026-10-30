"""Customer-facing errors without database paths or internal exception details."""
import streamlit as st


def show_error(exc, action="save your changes"):
    if isinstance(exc, (ValueError, PermissionError)):
        st.error(str(exc))
    elif isinstance(exc, FileNotFoundError):
        st.error("This document is currently unavailable. Contact the loan team and quote the request reference.")
    else:
        st.error(f"We couldn't {action}. Your action was not completed. Please try again. "
                 "If it keeps happening, contact the loan team.")
