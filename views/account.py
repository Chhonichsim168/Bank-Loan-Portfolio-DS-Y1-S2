"""My account - change password, enrol multi-factor sign-in."""

from __future__ import annotations

import hmac

import streamlit as st

from src import auth, ui


def render() -> None:
    user = auth.current_user()
    ui.page_header("My account", "Your password and sign-in security.", eyebrow="Account")
    st.markdown(f"**{user.display_name}** - {user.role_label} - `{user.username}`")

    left, right = st.columns(2, gap="large")
    with left:
        ui.section("Change password")
        with st.form("chg_pw", clear_on_submit=True, border=True):
            cur = st.text_input("Current password", type="password")
            pw1 = st.text_input("New password", type="password")
            pw2 = st.text_input("Repeat new password", type="password")
            go = st.form_submit_button("Change password", type="primary")
        if go:
            record = auth._read_users().get(user.username, {})
            ok, _ = auth.hash_password(cur, record.get("salt", "00"), int(record.get("iterations", auth.LEGACY_ITERATIONS)))
            if not hmac.compare_digest(ok, record.get("hash", "")):
                st.error("Current password is incorrect.")
            elif pw1 != pw2:
                st.error("The two new passwords do not match.")
            else:
                try:
                    auth.set_password(user.username, pw1)
                    st.success("Password changed.")
                except ValueError as exc:
                    st.error(str(exc))
    with right:
        ui.section("Multi-factor sign-in")
        if user.mfa_enabled:
            st.success("Enabled. You will be asked for a 6-digit code at every sign-in. "
                       "To remove it, ask an Administrator.")
        else:
            auth.render_mfa_enrol(user)
