"""User management - Administrators only."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from src import auth, ui
from src.data_pipeline import days_since, to_local


INACTIVE_DAYS = 90


def render() -> None:
    me = auth.current_user()
    ui.page_header("User management",
                   "Create accounts, change roles, disable people who have left and reset passwords. "
                   "Every action is written to the audit log.", eyebrow="Administration")

    users = pd.DataFrame(auth.list_users())
    users["role"] = users["role"].map(auth.ROLE_LABELS)
    # Date facts, shown in Phnom Penh time: when each person last signed in, and accounts that
    # have gone unused (a classic access-review finding - people who left but still have access).
    idle = days_since(users["last_login"].where(users["last_login"] != "", users["created_at"]))
    users["Days since sign-in"] = idle
    pw_age = days_since(users["password_changed_at"])
    users["Password age (days)"] = pw_age
    for col in ("created_at", "last_login", "password_changed_at"):
        users[col] = to_local(users[col]).replace("", "never")
    users = users.rename(columns={"username": "Username", "display_name": "Name", "role": "Role",
                                  "disabled": "Disabled", "must_change": "Must change password",
                                  "mfa": "MFA", "created_at": "Created", "last_login": "Last sign-in",
                                  "password_changed_at": "Password changed"})
    ui.table(users, hide_index=True, height=min(360, 60 + 36 * len(users)))
    stale = users[(~users["Disabled"]) & (users["Days since sign-in"].fillna(0) > INACTIVE_DAYS)]
    if len(stale):
        ui.note(f"<b>{', '.join(stale['Username'])}</b> ha{'ve' if len(stale) > 1 else 's'} not signed in for more "
                f"than {INACTIVE_DAYS} days. If they have left or changed role, disable the account below.",
                title="Inactive accounts", tone="warn")

    left, right = st.columns(2, gap="large")
    with left:
        ui.section("Add a user")
        with st.form("add_user", clear_on_submit=True, border=True):
            username = st.text_input("Username")
            name = st.text_input("Display name")
            role = st.selectbox("Role", list(auth.ROLE_LABELS), format_func=auth.ROLE_LABELS.get, index=2)
            go = st.form_submit_button("Create user", type="primary")
        if go:
            temp = auth.generate_temp_password()
            try:
                auth.create_user(username, name, role, temp, must_change=True, actor=me.username)
                st.success("Created. Give the user this one-time password - it is shown only now and "
                           "must be changed at first sign-in:")
                st.code(temp, language=None)
            except ValueError as exc:
                st.error(str(exc))

    with right:
        ui.section("Change a user")
        names = [u["username"] for u in auth.list_users()]
        target = st.selectbox("User", names, key="um_target")
        rec = next(u for u in auth.list_users() if u["username"] == target)
        new_role = st.selectbox("Role", list(auth.ROLE_LABELS), format_func=auth.ROLE_LABELS.get,
                                index=list(auth.ROLE_LABELS).index(rec["role"]), key=f"um_role_{target}")
        disabled = st.toggle("Account disabled", value=rec["disabled"], key=f"um_dis_{target}")
        if st.button("Save changes", key="um_save"):
            try:
                auth.update_user(target, role=new_role, disabled=disabled, actor=me.username)
                st.success("Saved.")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
        c1, c2 = st.columns(2)
        with c1:
            if st.button("Reset password", key="um_reset"):
                temp = auth.generate_temp_password()
                auth.set_password(target, temp, must_change=True, actor=me.username, action="password_reset")
                st.success("One-time password (shown once):")
                st.code(temp, language=None)
        with c2:
            if st.button("Reset MFA", key="um_mfa", disabled=not rec["mfa"]):
                auth.update_user(target, reset_mfa=True, actor=me.username)
                st.success("MFA removed; the user can enrol again.")
                st.rerun()

    from src.mode import lockout_enabled
    lock = (f"an account locks for {auth.LOCKOUT_MINUTES} minutes after {auth.MAX_FAILURES} failed sign-ins"
            if lockout_enabled() else "wrong passwords never lock an account")
    st.caption(f"Automatic sign-out after {auth.session_timeout_minutes()} idle minutes is off by default; each "
               f"person can switch it on with the toggle in the left rail; {lock}. "
               f"MFA is {'REQUIRED' if auth.mfa_required() else 'optional'} (CREDIT_DESK_REQUIRE_MFA).")
