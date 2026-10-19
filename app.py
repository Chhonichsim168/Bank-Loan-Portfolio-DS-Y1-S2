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
def filters() -> None:
    """Portfolio filters. Analysis pages read these; decisioning pages score independently."""
    c = state.ctx()
    book = c.book
    user = auth.current_user()

    if login_required():
        st.sidebar.markdown(
            f'<div class="cd-user"><span class="cd-user-name">{esc(user.display_name)}</span>'
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

    st.sidebar.markdown('<div class="cd-rail-label">Portfolio filters</div>',
                        unsafe_allow_html=True)

    if c.has_dates:
        st.sidebar.selectbox("Period", state.PERIODS, key="f_period",
                             help="Presets count back from the latest application in the book.")
        if st.session_state.get("f_period") == "Custom range":
            lo, hi = book["application_date"].min().date(), book["application_date"].max().date()
            kw = {} if "f_custom" in st.session_state else {"value": (lo, hi)}
            st.sidebar.date_input("From - to", min_value=lo, max_value=hi, key="f_custom",
                                  format="DD/MM/YYYY", **kw)
        if c.period is not None:
            st.sidebar.markdown(
                f'<div style="color:#8FB8B2;font-size:0.74rem;margin:-0.4rem 0 0.5rem 0;">'
                f"{esc(state.fmt_bounds(c.period))}</div>", unsafe_allow_html=True)

    st.sidebar.multiselect(
        "Property area", sorted(book["property_area"].unique()),
        key="f_area", format_func=lambda v: v.title(),
        placeholder="All areas",
    )
    st.sidebar.multiselect(
        "Employment", sorted(book["employment_status"].unique()),
        key="f_emp", format_func=lambda v: v.replace("_", "-").title(),
        placeholder="All types",
    )
    st.sidebar.multiselect(
        "Risk tier", state.RISK_ORDER, key="f_risk", placeholder="All tiers",
    )
    st.sidebar.selectbox(
        "Outcome", ["All", "Approved only", "Declined only"], key="f_outcome",
    )

    n = len(c.view)
    share = n / len(book) * 100 if len(book) else 0
    st.sidebar.markdown(
        f'<div style="color:#8FB8B2;font-size:0.78rem;padding:0.5rem 0 0.35rem 0;">'
        f"<b style='color:#FFFFFF'>{n:,}</b> of {len(book):,} applications "
        f"({share:.0f}%)</div>",
        unsafe_allow_html=True,
    )
    if c.filtered:
        st.sidebar.button("Clear filters", on_click=state.reset_filters)

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


def render_nav(visible: dict, page_objs: dict) -> None:
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
# LATE-PAYMENT NOTIFICATION (sidebar card on every page + one pop-up reminder per sign-in)
# =========================================================================================
@st.cache_data(ttl=300, show_spinner=False)
def _late_counts(signature: tuple, day: str) -> tuple[dict, int]:
    """Recomputed only when a loan or loan event is added (signature) or the day changes."""
    from src import loanbook, notifications
    book = loanbook.portfolio(day)
    return notifications.summary(notifications.overdue(book, day)), len(notifications.due_soon(book, day, 3))


def _late_payment_alert(loan_page=None) -> None:
    from src import notifications
    from src.data_pipeline import today_local
    try:
        s, soon = _late_counts(notifications.signature(), today_local().date().isoformat())
    except Exception:                       # a notification must never break a page
        return
    if not s["loans"] and not soon:
        return
    if s["loans"]:
        sev = s["by_severity"]
        parts = [f"{sev[k]} {k.lower()}" for k in ("Default", "Serious", "Warning", "Reminder") if sev[k]]
        red, dark, grey = "color:#B42318", "color:#7A271A", "color:#5B6879"
        st.sidebar.markdown(
            '<div class="cd-late" style="background:#FDECEA;border:1px solid #F4B4AE;border-left:5px solid #B42318;'
            'border-radius:8px;padding:9px 11px;margin:6px 0 4px 0;font-size:0.82rem;line-height:1.35">'
            f'<div style="font-weight:700;font-size:0.9rem;{red}">&#128276; {s["customers"]} customer(s) '
            f'late on payment</div>'
            f'<div style="{dark}"><b style="{dark}">{ui.money(s["arrears"])}</b> overdue on {s["loans"]} loan(s)</div>'
            f'<div style="{dark}">{esc(", ".join(parts))}</div>'
            + (f'<div style="{grey};margin-top:3px">{soon} more due in the next 3 days</div>' if soon else "")
            + '</div>', unsafe_allow_html=True)
        if loan_page is not None:
            st.sidebar.page_link(loan_page, label="Open late payments")
        if not st.session_state.get("_late_toast_shown"):
            st.session_state["_late_toast_shown"] = True
            if hasattr(st, "toast"):
                st.toast(f"{s['customers']} customer(s) are late on payment - {ui.money(s['arrears'])} overdue. "
                         "See Loan book -> Late payments.", icon="🔔")
    elif soon:
        st.sidebar.markdown(
            '<div style="background:#FEF4E6;border-left:5px solid #B54708;border-radius:8px;padding:8px 11px;'
            f'margin:6px 0 4px 0;font-size:0.82rem"><span style="color:#7A2E0E">&#128276; {soon} payment(s) due in '
            'the next 3 days. No customer is late.</span></div>', unsafe_allow_html=True)


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
        render_nav(visible, page_objs)
        _late_payment_alert(page_objs.get("Portfolio", {}).get("loanbook"))
        filters()
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
        _late_payment_alert()
        filters()
        _result.render_pending()
        page.run()
    else:
        # Older Streamlit still: fall back to a flat radio rail so the app still runs.
        flat = {title: fn for items in visible.values() for title, _, fn in items}
        choice = st.sidebar.radio("Navigate", list(flat.keys()), label_visibility="collapsed")
        _late_payment_alert()
        filters()
        _result.render_pending()
        flat[choice]()


run()
