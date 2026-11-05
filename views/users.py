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
    users["email"] = [f"{e} ✓" if e and v else (f"{e} (not verified)" if e else "")
                      for e, v in zip(users["email"], users["email_verified"])]
    users = users.drop(columns=["email_verified"])
    try:
        from src import customer_portal
        links = customer_portal.links_by_user()
        unlinked = customer_portal.unlinked_loans()
    except Exception:
        links, unlinked = {}, pd.DataFrame(columns=["loan_id", "customer_ref", "principal"])
    users.insert(4, "Linked loans", [", ".join(links.get(u, [])) for u in users["username"]])
    # Date facts, shown in Phnom Penh time: when each person last signed in, and accounts that
    # have gone unused (a classic access-review finding - people who left but still have access).
    idle = days_since(users["last_login"].where(users["last_login"] != "", users["created_at"]))
    users["Days since sign-in"] = idle
    pw_age = days_since(users["password_changed_at"])
    users["Password age (days)"] = pw_age
    for col in ("created_at", "last_login", "password_changed_at"):
        users[col] = to_local(users[col]).replace("", "never")
    users = users.rename(columns={"username": "Username", "display_name": "Name", "role": "Role",
                                  "email": "Email", "sign_in": "Sign-in",
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
            email = st.text_input("Email (Gmail for Google sign-in)", placeholder="name@gmail.com")
            role = st.selectbox("Role", list(auth.ROLE_LABELS), format_func=auth.ROLE_LABELS.get, index=2)
            google_only = st.checkbox("Google sign-in only (no password)",
                                      help="The person signs in with Continue with Google using the email "
                                           "above. No one-time password is issued.")
            loan_labels = {r.loan_id: f"{r.loan_id} · {r.customer_ref} · ${r.principal:,.0f}" for r in unlinked.itertuples()}
            chosen = st.multiselect("Link loan(s) - customers only", list(loan_labels), format_func=loan_labels.get,
                                    help="For a customer whose loan was issued at the branch: the loan appears in "
                                         "their portal as soon as they sign in. Check their ID card first.")
            send_mail = st.checkbox("Email the sign-in details to the person", value=True)
            go = st.form_submit_button("Create user", type="primary")
        if go:
            temp = auth.generate_temp_password()
            try:
                if chosen and role != "customer":
                    raise ValueError("Loans can only be linked to a Customer account. Choose the role Customer.")
                if chosen and not email.strip():
                    raise ValueError("Enter the customer's email so they can sign in and see the loan.")
                if google_only:
                    if not email.strip():
                        raise ValueError("Enter the person's Gmail address for a Google-only account.")
                    auth.create_user(username, name, role, temp, must_change=False, actor=me.username,
                                     email=email, email_verified=True)
                    auth.remove_password(username.strip(), actor=me.username)
                    st.success(f"Created. {auth.mask_email(email)} can now press Continue with Google on the "
                               "sign-in page.")
                else:
                    auth.create_user(username, name, role, temp, must_change=True, actor=me.username,
                                     email=email, email_verified=bool(email.strip()))
                    st.success("Created. Give the user this one-time password - it is shown only now and "
                               "must be changed at first sign-in" +
                               (" (or they can use Continue with Google with their email):" if email.strip() else ":"))
                    st.code(temp, language=None)
                _after_create(me, username.strip(), name, email, role, chosen, send_mail,
                              None if google_only else temp)
            except (ValueError, PermissionError) as exc:
                st.error(str(exc))

    with right:
        ui.section("Change a user")
        names = [u["username"] for u in auth.list_users()]
        target = st.selectbox("User", names, key="um_target")
        rec = next(u for u in auth.list_users() if u["username"] == target)
        new_role = st.selectbox("Role", list(auth.ROLE_LABELS), format_func=auth.ROLE_LABELS.get,
                                index=list(auth.ROLE_LABELS).index(rec["role"]), key=f"um_role_{target}")
        disabled = st.toggle("Account disabled", value=rec["disabled"], key=f"um_dis_{target}")
        new_email = st.text_input("Email", value=rec["email"], key=f"um_email_{target}",
                                  help="An address you enter here counts as verified, so the person can sign in "
                                       "with Google using it. Leave empty to remove it.")
        if rec["role"] == "customer":
            lk = links.get(target, [])
            st.caption("Linked loans: " + (", ".join(lk) if lk else "none yet - link them below or in "
                                                                   "Customer requests > Accounts for existing loans"))
            if loan_labels_all := {r.loan_id: f"{r.loan_id} · {r.customer_ref}" for r in unlinked.itertuples()}:
                c_link, c_btn = st.columns([3, 1.2], vertical_alignment="bottom")
                add = c_link.multiselect("Link more loan(s)", list(loan_labels_all), format_func=loan_labels_all.get,
                                         key=f"um_link_{target}")
                if c_btn.button("Link", key=f"um_link_go_{target}", disabled=not add):
                    try:
                        from src import customer_portal
                        for lid in add:
                            customer_portal.link_existing(lid, target)
                        st.success(f"Linked {', '.join(add)} to {target}.")
                        st.rerun()
                    except (ValueError, PermissionError) as exc:
                        st.error(str(exc))
            if st.button("Resend sign-in email", key=f"um_resend_{target}", disabled=not rec["email"],
                         help="Emails the customer how to sign in. If they use a password, a new one-time "
                              "password is issued (the old one stops working)."):
                try:
                    from src import customer_portal
                    info, problem = customer_portal.resend_sign_in(target)
                    st.success("Sign-in email sent." if not problem else f"Not sent: {problem}")
                    if info.get("temp_password"):
                        st.code(info["temp_password"], language=None)
                except (ValueError, PermissionError) as exc:
                    st.error(str(exc))
        if st.button("Save changes", key="um_save"):
            try:
                auth.update_user(target, role=new_role, disabled=disabled, actor=me.username)
                if auth.normalize_email(new_email) != auth.normalize_email(rec["email"]) or (
                        new_email.strip() and not rec["email_verified"]):
                    auth.set_email(target, new_email, verified=True, actor=me.username)
                st.success("Saved.")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
        c1, c2 = st.columns(2)
        with c1:
            if st.button("Reset password", key="um_reset",
                         help="Issues a one-time password. Google sign-in keeps working."):
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


def _after_create(me, username, name, email, role, loans, send_mail, temp) -> None:
    """Customer created here: link the chosen loans and email the sign-in details."""
    from src import customer_portal
    for lid in loans:
        customer_portal.link_existing(lid, username)
    if loans:
        st.success(f"Linked {', '.join(loans)} - they appear in the customer's portal at sign-in.")
    if send_mail and email.strip() and role == "customer":
        info = {"username": username, "email": auth.normalize_email(email), "temp_password": temp, "created": True}
        problem = customer_portal.send_account_invitation(info, name)
        st.caption("Sign-in email: " + ("sent ✅" if not problem else problem))
