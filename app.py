"""
Credit Desk — loan portfolio analytics and decisioning console
==============================================================

Run with:

    streamlit run app.py

The shell only does four things: configure the page, install the theme, render the
navigation rail and the portfolio filters, and hand control to a page. All content lives
in `views/`, all shared state in `src/state.py`, all design tokens in `src/ui.py`.
"""

from __future__ import annotations

import inspect
import base64
import sys
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def _settings_from_hosting_secrets() -> None:
    """On a hosting service (e.g. Streamlit Community Cloud) the CREDIT_DESK_* switches are typed
    into its Secrets box (.streamlit/secrets.toml). Copy them into the environment BEFORE the app
    modules read them. A variable already set in the real environment wins; no secrets = no-op."""
    import os
    try:
        items = dict(st.secrets)
    except Exception:                      # no secrets file: running locally
        return
    for key, value in items.items():
        if key.startswith("CREDIT_DESK_") and key not in os.environ and not isinstance(value, dict):
            os.environ[key] = str(value)


_settings_from_hosting_secrets()

from src import state, ui  # noqa: E402
from src import auth  # noqa: E402
from src.mode import login_required  # noqa: E402
from src.security import esc  # noqa: E402
from views import (account, batch, drivers, governance, loan_book, model,  # noqa: E402
                   overview, policy, queue, segments, underwrite, users)
from views import _result  # noqa: E402
from views import backup_admin, customer, customer_requests, support  # noqa: E402

st.set_page_config(
    page_title="Credit Desk — Loan Portfolio Analytics",
    page_icon="◧",
    layout="wide",
    initial_sidebar_state="auto",
    menu_items={"about": "Credit Desk — loan portfolio analytics and decisioning."},
)


def _inject_sidebar_toggle() -> None:
    """
    A visible, always-on button for opening/closing the sidebar, that does not depend
    on knowing Streamlit's own internal button for this. Streamlit's built-in control
    changes shape (and its underlying `data-testid`) across versions, which is why a
    CSS-only fix can silently stop matching after an update and leave the button
    invisible with no error anywhere. This works a different way: it draws its own
    fixed pill in the corner of the screen, and when clicked, searches the real page
    for whichever native show/hide control currently exists and clicks it directly —
    so it keeps working even if that control's internal markup changes again later.
    """
    components.html(
        """
        <script>
        (function () {
            const doc = window.parent.document;
            // Streamlit replaces the component iframe on page changes. Rebind the
            // button instead of retaining handlers/timers owned by the old iframe.
            const previous = doc.getElementById('cd-sidebar-toggle');
            if (previous) previous.remove();
            if (window.parent.__creditDeskMenuTimer) {
                window.parent.clearInterval(window.parent.__creditDeskMenuTimer);
            }

            const btn = doc.createElement('button');
            btn.id = 'cd-sidebar-toggle';
            btn.type = 'button';
            btn.setAttribute('aria-label', 'Open navigation menu');
            btn.title = 'Open navigation menu';
            btn.innerHTML = '&#9776;&nbsp; Menu';
            btn.style.cssText = [
                'position:fixed', 'top:14px', 'left:14px', 'z-index:2147483647',
                'background:#07453F', 'color:#FFFFFF', 'border:1px solid #6FD3C4',
                'border-radius:6px', 'padding:0.45rem 0.9rem', 'font-size:0.85rem',
                'font-weight:700', 'font-family:"IBM Plex Sans",sans-serif',
                'cursor:pointer', 'box-shadow:1px 2px 8px rgba(0,0,0,0.3)',
                'display:none', 'align-items:center',
            ].join(';');
            btn.onmouseenter = function () { btn.style.background = '#0B6B62'; };
            btn.onmouseleave = function () { btn.style.background = '#07453F'; };

            function findRealToggle() {
                const selectors = [
                    '[data-testid="stSidebarCollapsedControl"] button',
                    '[data-testid="stSidebarCollapsedControl"]',
                    '[data-testid="collapsedControl"] button',
                    '[data-testid="collapsedControl"]',
                    '[data-testid="stSidebarHeader"] button',
                    'button[data-testid="stSidebarCollapseButton"]',
                    'button[aria-label*="sidebar" i]',
                    'button[title*="sidebar" i]',
                ];
                for (const sel of selectors) {
                    const el = doc.querySelector(sel);
                    if (el) {
                        const target = el.matches('button') ? el : el.querySelector('button');
                        if (target && target.getBoundingClientRect().width > 0) return target;
                    }
                }
                return null;
            }

            btn.addEventListener('click', function () {
                const target = findRealToggle();
                if (target) target.click();
            });

            doc.body.appendChild(btn);

            // Only show our button while the sidebar is actually collapsed — when it's
            // open, Streamlit's own header already has a working close control, and we
            // don't want to sit on top of it.
            function sync() {
                const sb = doc.querySelector('[data-testid="stSidebar"]');
                const rect = sb && sb.getBoundingClientRect();
                const collapsed = !rect || rect.width < 5 || rect.right <= 5
                    || sb.getAttribute('aria-expanded') === 'false';
                btn.style.display = collapsed ? 'flex' : 'none';
            }
            window.parent.__creditDeskMenuTimer = window.parent.setInterval(sync, 300);
            sync();
        })();
        </script>
        """,
        height=0,
    )


ui.inject_theme()
_inject_sidebar_toggle()
state.init()

if not login_required():
    # No sign-in (the default): open straight into the app as the single local operator.
    auth.start_local_session()
else:
    # Idle timeout, disabled-account check and sign-in gate.
    if not auth.check_session():
        st.markdown("""
            <style>
            [data-testid="stSidebar"],
            [data-testid="stSidebarCollapsedControl"],
            [data-testid="collapsedControl"],
            #cd-sidebar-toggle {
                display: none !important;
            }
            </style>
        """, unsafe_allow_html=True)
        auth.render_login()
        st.stop()

    # A one-time password must be replaced (and MFA enrolled, if required) before anything else.
    _setup = auth.pending_setup(auth.current_user())
    if _setup:
        auth.render_forced_setup(auth.current_user(), _setup)
        st.stop()


# =========================================================================================
# NAVIGATION RAIL
# =========================================================================================
def user_panel(account_page=None) -> None:
    """Who is signed in, Sign out, and the source / version footer - bottom of the rail.
    (The portfolio filters are a bar at the top of the pages that use them: views/_filters.py.)"""
    c = state.ctx()
    user = auth.current_user()
    if login_required():
        from src import customer_portal
        import base64
        identity = customer_portal.profile()
        name = identity.get("full_name") or user.display_name
        st.sidebar.markdown(
            f'<div class="cd-user" style="border-top:1px solid rgba(255,255,255,0.12);'
            f'margin-top:0.9rem;padding-top:0.9rem">'
            f'<span class="cd-user-name">{esc(name)}</span>'
            f'<span class="cd-user-role">{esc(user.role_label)}</span></div>',
            unsafe_allow_html=True,
        )
        with st.sidebar.container(key="staff_account_actions"):
            signout, settings = st.columns(2,gap="small")
            signout.button("Sign out",key="_signout",on_click=_sign_out,**ui.STRETCH)
            if account_page is not None and settings.button("My account",key="_staff_account",**ui.STRETCH):
                st.switch_page(account_page)
        st.sidebar.toggle(
            f"Auto sign-out after {auth.session_timeout_minutes()} min idle",
            value=auth.auto_logout_enabled(user.username), key="_auto_logout",
            on_change=lambda: auth.set_auto_logout(user.username, st.session_state["_auto_logout"]),
            help="Off: you stay signed in until you press Sign out. On: you are signed out after "
                 "this many idle minutes (safer on a shared computer).")
        if auth.demo_mode():
            st.sidebar.warning("Trial mode: simple passwords. Not for real data.")
    st.sidebar.markdown(
        f'<div style="color:#6E9A94;font-size:0.72rem;padding:1.1rem 0 0.3rem 0;'
        f'border-top:1px solid rgba(255,255,255,0.12);margin-top:0.9rem;">'
        f"Source: {esc(c.source_name)}<br>Policy v{c.policy_version} · model {c.model_version}<br>"
        f"Decision support only — not an underwriting system."
        f"</div>",
        unsafe_allow_html=True,
    )


def staff_profile_header(profile_page):
    from src import customer_portal
    import base64
    user = auth.current_user()
    identity = customer_portal.profile()
    name = identity.get("full_name") or user.display_name
    initials = "".join(word[0] for word in name.split()[:2]).upper() or "U"
    photo = customer_portal.profile_photo()
    st.markdown("""<style>
      [data-testid="stSidebarHeader"]::after {content:none;}
      [data-testid="stSidebarHeader"] {height:48px!important;min-height:48px!important;
        padding:4px 12px!important;margin:0 0 8px!important;border:0;display:flex;justify-content:flex-end;}
      [data-testid="stSidebarHeader"] button {position:static!important;margin:0!important;min-width:40px;min-height:40px;}
      .st-key-staff_identity_header {border-bottom:1px solid rgba(255,255,255,.15);padding-bottom:.8rem;margin-bottom:.5rem;}
      .st-key-staff_identity_header [data-testid="stHorizontalBlock"],
      .st-key-staff_account_actions [data-testid="stHorizontalBlock"] {flex-wrap:nowrap!important;align-items:center;}
      .st-key-staff_identity_header [data-testid="stColumn"],
      .st-key-staff_account_actions [data-testid="stColumn"] {min-width:0;}
      .st-key-staff_profile_avatar button {width:44px!important;min-width:44px!important;height:44px!important;
        min-height:44px!important;border-radius:50%!important;padding:0!important;background:#D3F4EC!important;
        color:#07453F!important;border:2px solid #87DACA!important;font-weight:700;box-shadow:0 0 0 3px rgba(255,255,255,.08);}
      .st-key-staff_profile_avatar button * {color:#07453F!important;}
      .st-key-staff_profile_avatar button:focus-visible {outline:3px solid white;outline-offset:3px;}
    </style>""",unsafe_allow_html=True)
    if photo:
        encoded=base64.b64encode(photo).decode("ascii")
        st.markdown('<style>.st-key-staff_profile_avatar button {'
            f'background-image:url("data:image/jpeg;base64,{encoded}")!important;'
            'background-size:cover!important;background-position:center!important;}'
            '.st-key-staff_profile_avatar button p {color:transparent!important;}</style>',unsafe_allow_html=True)
    with st.sidebar.container(key="staff_identity_header"):
        brand,avatar=st.columns([3,1],vertical_alignment="center",gap="small")
        brand.markdown('<span style="color:white;font-size:1.05rem;font-weight:600;white-space:nowrap">Credit Desk</span>',unsafe_allow_html=True)
        if avatar.button(initials,key="staff_profile_avatar",help="My profile"):
            st.switch_page(profile_page)


PAGES = {
    "Portfolio": [
        ("Overview", "overview", overview.render),
        ("Segments", "segments", segments.render),
        ("Approval drivers", "drivers", drivers.render),
        ("Loan book", "loanbook", loan_book.render),
    ],
    "Decisioning": [
        ("Customer requests", "requests", customer_requests.render),
        ("Customer support", "support_staff", support.render_staff),
        ("Score an application", "score", underwrite.render),
        ("Score a file", "batch", batch.render),
        ("Policy and cut-offs", "policy", policy.render),
        ("Decision queue", "queue", queue.render),
    ],
    "Governance": [
        ("Model performance", "model", model.render),
        ("Data and governance", "data", governance.render),
    ],
    "Administration": [
        ("User management", "users", users.render),
        ("Backup and restore", "backups", backup_admin.render),
    ],
    "Account": [
        ("My profile", "staff_profile", support.render_staff_profile),
        ("My account", "account", account.render),
    ],
}


def _sign_out() -> None:
    auth.log_out()


def _nav_supports_hidden_position() -> bool:
    """st.navigation can hide its own auto-drawn menu (position='hidden') from
    Streamlit 1.36 onward. When it can't, we fall back to that built-in menu — always
    expanded, no collapse arrow — rather than risk a broken nav on an older install."""
    return hasattr(st, "navigation") and "position" in inspect.signature(st.navigation).parameters


def _toggle_nav_group(group: str) -> None:
    key = f"_navopen_{group}"
    st.session_state[key] = not st.session_state.get(key, True)


def render_nav(visible: dict, page_objs: dict, late_customers: int = 0) -> None:
    """
    Our own collapsible nav rail, drawn in place of st.navigation's built-in menu.

    st.navigation groups pages under a section label, but that label is static — it
    can't be clicked to collapse the section, so every page in every section is always
    on screen at once. Here each section header is a real button carrying a plain
    text arrow (▾ open / ▸ collapsed, not an icon font, so it never depends on a
    network connection to render) that toggles whether its pages are shown.
    """
    for group, items in visible.items():
        if group == "Account":
            continue
        open_key = f"_navopen_{group}"
        is_open = st.session_state.get(open_key, True)
        with st.sidebar.container(key=f"navgrp_{group}"):
            st.button(
                f"{'▾' if is_open else '▸'}  {group}",
                key=f"_navbtn_{group}",
                on_click=_toggle_nav_group, args=(group,),
                **ui.STRETCH,
            )
        if is_open:
            for title, slug, _fn in items:
                if slug == "loanbook" and late_customers:
                    # Red count badge: how many customers are late, visible from every page.
                    title = f"{title}  :red-badge[{late_customers} late]"
                st.sidebar.page_link(page_objs[group][slug], label=title)


def _missing_libraries_banner() -> None:
    """One line at the top of every page when an optional library is missing, with the fix."""
    from src import deps
    gone = deps.missing()
    if gone:
        ui.note("Some features are switched off because these libraries are not installed: <b>"
                + ", ".join(gone) + "</b> (" + "; ".join(deps.FEATURES[g] for g in gone) + "). "
                "Close the app and run <code>" + esc(deps.install_command(gone)) + "</code>, "
                "or start it again with START Credit Desk, which installs them.",
                title="Missing libraries", tone="warn")


def _load_sample_data() -> None:
    """First start of an empty system only: sample decisions and loans so every page can be
    tried at once (src/sample_data.py; off with CREDIT_DESK_SAMPLE_DATA=0)."""
    from src import sample_data
    if not sample_data.enabled() or sample_data.marker_path().exists():
        return
    with st.spinner("First start: loading sample loans and decisions for testing..."):
        try:
            sample_data.seed_if_empty(state.ctx)
        except Exception as exc:          # sample data must never stop the app
            sample_data._write_marker(f"failed: {exc}")
            st.warning(f"Sample data could not be loaded ({exc}). The app works normally without it.")


# =========================================================================================
# LATE-PAYMENT NOTIFICATION
# A red count badge on "Loan book" in the menu (always visible, takes no space) plus one
# slim alert bar across the top of the page - where the eye lands first - with a button
# straight to the list. The bar can be hidden for the rest of the session; the badge stays.
# =========================================================================================
@st.cache_data(ttl=300, show_spinner=False)
def _late_counts(signature: tuple, day: str) -> tuple[dict, int]:
    """Recomputed only when a loan or loan event is added (signature) or the day changes."""
    from src import loanbook, notifications
    book = loanbook.portfolio(day)
    return notifications.summary(notifications.overdue(book, day)), len(notifications.due_soon(book, day, 3))


def _late_status() -> tuple[dict, int] | None:
    from src import notifications
    from src.data_pipeline import today_local
    try:
        return _late_counts(notifications.signature(), today_local().date().isoformat())
    except Exception:                       # a notification must never break a page
        return None


SEVERITY_CHIP = {"Default": ("#FFFFFF", "#912018"), "Serious": ("#FFFFFF", "#C4320A"),
                 "Warning": ("#7A2E0E", "#FEDF89"), "Reminder": ("#344054", "#EAECF0")}


def _hide_late_banner() -> None:
    st.session_state["_late_banner_hidden"] = True


def _late_banner(status, loan_page=None, on_loan_page: bool = False) -> None:
    """The alert bar at the top of the page. Not drawn on Loan book itself (its first tab
    is the full list) or after the user hides it for this session."""
    if not status or on_loan_page or st.session_state.get("_late_banner_hidden"):
        return
    s, soon = status
    if s["loans"]:
        sev = s["by_severity"]
        chips = "".join(
            f'<span class="cd-late-chip" style="color:{fg};background:{bg}">{sev[k]} {k.lower()}</span>'
            for k, (fg, bg) in SEVERITY_CHIP.items() if sev.get(k))
        text = (f'<div class="cd-late-title">&#128276; {s["customers"]} customer(s) are late on payment</div>'
                f'<div class="cd-late-body"><b>{ui.money(s["arrears"])}</b> overdue on {s["loans"]} loan(s)'
                + (f' &middot; {soon} more due in the next 3 days' if soon else "")
                + f'</div><div class="cd-late-chips">{chips}</div>')
        tone = "cd-late-red"
    elif soon:
        text = (f'<div class="cd-late-title">&#128276; {soon} payment(s) due in the next 3 days</div>'
                '<div class="cd-late-body">No customer is late. A reminder call now keeps it that way.</div>')
        tone = "cd-late-amber"
    else:
        return
    with st.container(key=f"cd_late_banner_{tone}"):
        left, mid, right = st.columns([5.2, 1.7, 0.45], vertical_alignment="center", gap="small")
        left.markdown(text, unsafe_allow_html=True)
        if loan_page is not None:
            mid.page_link(loan_page, label="Open late payments  →")
        right.button("✕", key="_late_hide", on_click=_hide_late_banner, help="Hide for this session")


def run() -> None:
    user = auth.current_user()
    if user.role == "customer":
        from src.customer_i18n import language_picker, t
        language_picker()
        # Customer navigation never loads employee data, sample seeding, portfolio
        # alerts or pending underwriting results, including on a direct page URL.
        if hasattr(st, "navigation"):
            from views import loan_details, request_details, customer_help
            help_page = st.Page(customer_help.render,title=t("Help / FAQ"),url_path="help")
            st.session_state["_customer_help_page"] = help_page
            request_page = st.Page(request_details.render, title=t("Request details"), url_path="request_details")
            st.session_state["_customer_request_details_page"] = request_page
            details_page = st.Page(loan_details.render, title=t("Loan details"), url_path="loan_details")
            st.session_state["_customer_loan_details_page"] = details_page
            home_page = st.Page(customer.render, title=t("My customer portal"), url_path="customer", default=True)
            st.session_state["_customer_home_page"] = home_page
            profile_page = st.Page(customer.render_profile, title=t("My profile"), url_path="profile")
            st.session_state["_customer_profile_page"] = profile_page
            account_page = st.Page(account.render, title=t("My account"), url_path="account")
            notifications_page = st.Page(customer.render_notifications, title=t("Notifications"), url_path="notifications")
            support_page = st.Page(support.render_customer, title=t("Messages"), url_path="support")
            st.session_state["_customer_support_page"] = support_page
            hidden_nav = _nav_supports_hidden_position()
            page = st.navigation([home_page, profile_page, account_page, notifications_page, support_page, details_page, request_page, help_page],
                                 **({"position": "hidden"} if hidden_nav else {}))
            from src import customer_portal
            notices = customer_portal.my_notifications()
            st.session_state["_customer_notifications_snapshot"] = {"username":user.username,"items":notices}
            if getattr(page, "url_path", "") == "notifications":
                customer_portal.mark_notifications_read([n["id"] for n in notices])
                notices = [{**n, "unread": False} for n in notices]
            customer.notification_bell(notices, notifications_page)
            st.markdown("""<style>
                [data-testid="stSidebarHeader"]::after { content: none; }
                [data-testid="stSidebarHeader"] {
                    height: 48px !important; min-height: 48px !important;
                    padding: 4px 12px !important; margin: 0 0 8px !important;
                    border: 0; overflow: visible; display: flex; justify-content: flex-end;
                }
                [data-testid="stSidebarHeader"] button {
                    position: static !important; margin: 0 !important;
                    min-width: 40px; min-height: 40px;
                }
                .st-key-customer_identity_header { padding-left: 0;
                    border-bottom: 1px solid rgba(255,255,255,.15); padding-bottom: .8rem; }
                .st-key-customer_identity_header [data-testid="stHorizontalBlock"] {
                    flex-wrap: nowrap; align-items: center;
                }
                .st-key-customer_identity_header [data-testid="stColumn"] { min-width: 0; }
                .st-key-customer_profile_avatar button {
                    width: 44px !important; min-width: 44px !important; height: 44px !important;
                    min-height: 44px !important; border-radius: 50% !important;
                    padding: 0 !important; background: #D3F4EC !important;
                    color: #07453F !important; border: 2px solid #87DACA !important;
                    font-weight: 700; box-shadow: 0 0 0 3px rgba(255,255,255,.08);
                }
                .st-key-customer_profile_avatar button:hover {
                    background: #FFFFFF !important; border-color: #FFFFFF !important;
                }
                .st-key-customer_profile_avatar button * { color: #07453F !important; }
                .st-key-customer_profile_avatar button:focus-visible {
                    outline: 3px solid #FFFFFF; outline-offset: 3px;
                }
                .st-key-customer_account_actions [data-testid="stHorizontalBlock"] { flex-wrap: nowrap; }
                .st-key-customer_account_actions [data-testid="stColumn"] { min-width: 0; }
            </style>""", unsafe_allow_html=True)
            profile_name = customer_portal.profile().get("full_name") or user.display_name
            initials = "".join(word[0] for word in profile_name.split()[:2]).upper() or "U"
            avatar_image = customer_portal.profile_photo()
            if avatar_image:
                encoded = base64.b64encode(avatar_image).decode("ascii")
                st.markdown('<style>.st-key-customer_profile_avatar button,'
                    '.st-key-customer_profile_avatar button:hover {'
                    f'background-image:url("data:image/jpeg;base64,{encoded}") !important;'
                    'background-size:cover !important;background-position:center !important;}'
                    '.st-key-customer_profile_avatar button p {color:transparent !important;}</style>',
                    unsafe_allow_html=True)
            with st.sidebar.container(key="customer_identity_header"):
                brand, avatar = st.columns([3, 1], vertical_alignment="center", gap="small")
                brand.markdown('<span style="color:white;font-size:1.05rem;font-weight:600;'
                               'white-space:nowrap">Credit Desk</span>', unsafe_allow_html=True)
                if avatar.button(initials, key="customer_profile_avatar", help=t("My profile")):
                    st.switch_page(profile_page)
            if hidden_nav:
                st.sidebar.page_link(home_page, label=t("My customer portal"))
                st.sidebar.page_link(details_page, label=t("Loan details"))
                st.sidebar.page_link(request_page, label=t("Request details"))
                st.sidebar.page_link(help_page, label=t("Help / FAQ"))
                from src import customer_support
                unread_support = int(customer_support.tickets()["unread"].sum())
                support_label = t("Messages") + (f" :red-badge[{unread_support}]" if unread_support else "")
                st.sidebar.page_link(support_page, label=support_label)
            st.sidebar.markdown(f"**{esc(user.display_name)}**")
            with st.sidebar.container(key="customer_account_actions"):
                signout_col, account_col = st.columns(2, gap="small")
                signout_col.button(t("Sign out"), key="_customer_signout", on_click=_sign_out, **ui.STRETCH)
                if account_col.button(t("My account"), key="_customer_account", **ui.STRETCH):
                    st.switch_page(account_page)
            page.run()
        else:
            from views import loan_details, request_details, customer_help
            customer_pages = {"Help / FAQ": customer_help.render, "My customer portal": customer.render, "Loan details": loan_details.render, "Request details": request_details.render,
                              "My profile": customer.render_profile, "My account": account.render,
                              "Notifications": customer.render_notifications, "Customer support": support.render_customer}
            choice = st.sidebar.radio("Customer menu", list(customer_pages))
            st.sidebar.button("Sign out", key="_customer_signout", on_click=_sign_out)
            customer_pages[choice]()
        return
    _missing_libraries_banner()
    _load_sample_data()
    user = auth.current_user()
    visible = {
        group: [item for item in items if auth.can_access(user.role, item[1])]
        for group, items in PAGES.items()
    }
    visible = {group: items for group, items in visible.items() if items}

    if _nav_supports_hidden_position():
        page_objs = {
            group: {
                slug: st.Page(fn, title=title, url_path=slug,
                               default=(slug == "overview"))
                for title, slug, fn in items
            }
            for group, items in visible.items()
        }
        flat_pages = [p for group_pages in page_objs.values() for p in group_pages.values()]
        page = st.navigation(flat_pages, position="hidden")
        late = _late_status()
        staff_profile_header(page_objs["Account"]["staff_profile"])
        render_nav(visible, page_objs, late_customers=late[0]["customers"] if late else 0)
        user_panel(page_objs["Account"]["account"])
        loan_page = page_objs.get("Portfolio", {}).get("loanbook")
        _late_banner(late, loan_page, on_loan_page=getattr(page, "url_path", "") == "loanbook")
        _result.render_pending()
        page.run()
    elif hasattr(st, "navigation"):
        # Older Streamlit without position="hidden": use its own always-expanded menu.
        nav = {
            group: [
                st.Page(fn, title=title, url_path=slug,
                        default=(slug == "overview"))
                for title, slug, fn in items
            ]
            for group, items in visible.items()
        }
        page = st.navigation(nav)
        user_panel()
        _late_banner(_late_status())
        _result.render_pending()
        page.run()
    else:
        # Older Streamlit still: fall back to a flat radio rail so the app still runs.
        flat = {title: fn for items in visible.values() for title, _, fn in items}
        choice = st.sidebar.radio("Navigate", list(flat.keys()), label_visibility="collapsed")
        user_panel()
        _late_banner(_late_status())
        _result.render_pending()
        flat[choice]()


run()
