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

st.set_page_config(
    page_title="Credit Desk — Loan Portfolio Analytics",
    page_icon="◧",
    layout="wide",
    initial_sidebar_state="expanded",
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
            if (doc.getElementById('cd-sidebar-toggle')) return;

            const btn = doc.createElement('button');
            btn.id = 'cd-sidebar-toggle';
            btn.type = 'button';
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
                    'button[aria-label*="sidebar" i]',
                    'button[title*="sidebar" i]',
                ];
                for (const sel of selectors) {
                    const el = doc.querySelector(sel);
                    if (el) return el;
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
                const collapsed = !sb || sb.offsetWidth < 5
                    || sb.getAttribute('aria-expanded') === 'false';
                btn.style.display = collapsed ? 'flex' : 'none';
            }
            setInterval(sync, 300);
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
def user_panel() -> None:
    """Who is signed in, Sign out, and the source / version footer - bottom of the rail.
    (The portfolio filters are a bar at the top of the pages that use them: views/_filters.py.)"""
    c = state.ctx()
    user = auth.current_user()
    if login_required():
        st.sidebar.markdown(
            f'<div class="cd-user" style="border-top:1px solid rgba(255,255,255,0.12);'
            f'margin-top:0.9rem;padding-top:0.9rem">'
            f'<span class="cd-user-name">{esc(user.display_name)}</span>'
            f'<span class="cd-user-role">{esc(user.role_label)}</span></div>',
            unsafe_allow_html=True,
        )
        st.sidebar.button("Sign out", key="_signout", on_click=_sign_out)
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


PAGES = {
    "Portfolio": [
        ("Overview", "overview", overview.render),
        ("Segments", "segments", segments.render),
        ("Approval drivers", "drivers", drivers.render),
        ("Loan book", "loanbook", loan_book.render),
    ],
    "Decisioning": [
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
    ],
    "Account": [
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
        render_nav(visible, page_objs, late_customers=late[0]["customers"] if late else 0)
        user_panel()
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
