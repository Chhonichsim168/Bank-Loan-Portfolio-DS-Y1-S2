"""
The portfolio filter bar - drawn at the top of the pages that use the filters
(Portfolio overview, Segments, Approval drivers, Policy and cut-offs).

One card with:
  * the five filters side by side (Period, Property area, Employment, Risk tier, Outcome),
  * the result in large type ("514 of 2,000 applications - 26%"),
  * one chip per active filter, each with its own x to remove just that filter, and Clear all.

Pages that do not use the filters (Score an application, Loan book, Decision queue ...) do not
show them at all, so nobody changes a filter and wonders why nothing happened.
The values live in session state (keys f_period, f_area, f_emp, f_risk, f_outcome, f_custom),
so a choice made on Overview is still there on Segments.
"""

from __future__ import annotations

from html import escape as esc

import streamlit as st

from src import state

ALL_OUTCOMES = ["All", "Approved only", "Declined only"]


# ---- remove one filter (chip x) -------------------------------------------------------------
def _clear(key: str) -> None:
    if key == "f_period":
        st.session_state["f_period"] = "All time"
        st.session_state.pop("f_custom", None)
    elif key == "f_outcome":
        st.session_state["f_outcome"] = "All"
    else:
        st.session_state[key] = []


def _drop_value(key: str, value: str) -> None:
    st.session_state[key] = [v for v in st.session_state.get(key, []) if v != value]


def _chips(c) -> list[tuple[str, str, str, str | None]]:
    """(chip key, label, session key, value-or-None) for every active filter."""
    ss = st.session_state
    out = []
    if c.period is not None:
        out.append(("period", f"Period: {state.fmt_bounds(c.period)}", "f_period", None))
    for v in ss.get("f_area", []):
        out.append((f"area_{v}", f"Area: {v.title()}", "f_area", v))
    for v in ss.get("f_emp", []):
        out.append((f"emp_{v}", f"Employment: {v.replace('_', '-').title()}", "f_emp", v))
    for v in ss.get("f_risk", []):
        out.append((f"risk_{v}", f"Risk: {v}", "f_risk", v))
    if ss.get("f_outcome", "All") != "All":
        out.append(("outcome", ss["f_outcome"], "f_outcome", None))
    return out


def filter_bar(c) -> None:
    """Draw the filter card. ``c`` is the page's state.ctx()."""
    book = c.book
    with st.container(key="cd_filterbar"):
        st.markdown('<div class="cd-fb-title">Filter the portfolio</div>', unsafe_allow_html=True)

        custom = st.session_state.get("f_period") == "Custom range"
        widths = [1.25, 1, 1, 1, 0.95] + ([1.35] if custom else [])
        cols = st.columns(widths, gap="small")
        if c.has_dates:
            cols[0].selectbox("Period", state.PERIODS, key="f_period",
                              help="Presets count back from the latest application in the book.")
        else:
            cols[0].selectbox("Period", ["All time"], key="f_period", disabled=True)
        cols[1].multiselect("Property area", sorted(book["property_area"].unique()), key="f_area",
                            format_func=lambda v: v.title(), placeholder="All areas")
        cols[2].multiselect("Employment", sorted(book["employment_status"].unique()), key="f_emp",
                            format_func=lambda v: v.replace("_", "-").title(), placeholder="All types")
        cols[3].multiselect("Risk tier", state.RISK_ORDER, key="f_risk", placeholder="All tiers")
        cols[4].selectbox("Outcome", ALL_OUTCOMES, key="f_outcome")
        if custom:
            lo, hi = book["application_date"].min().date(), book["application_date"].max().date()
            kw = {} if "f_custom" in st.session_state else {"value": (lo, hi)}
            cols[5].date_input("From - to", min_value=lo, max_value=hi, key="f_custom",
                               format="DD/MM/YYYY", **kw)

        n, total = len(c.view), len(book)
        share = n / total * 100 if total else 0
        chips = _chips(c)
        with st.container(key="cd_fb_result", horizontal=True, vertical_alignment="center", gap="small"):
            st.markdown(
                f'<div class="cd-fb-count"><span class="cd-fb-n">{n:,}</span>'
                f'<span class="cd-fb-of"> of {total:,} applications &middot; {share:.0f}%</span></div>',
                unsafe_allow_html=True, width="content")
            if not chips:
                st.markdown('<span class="cd-fb-whole">Showing the whole book</span>',
                            unsafe_allow_html=True, width="content")
            for chip_key, label, key, value in chips:
                if value is None:
                    st.button(f"{label}  ✕", key=f"cd_chip_{chip_key}", on_click=_clear, args=(key,),
                              help="Remove this filter")
                else:
                    st.button(f"{label}  ✕", key=f"cd_chip_{chip_key}", on_click=_drop_value,
                              args=(key, value), help="Remove this filter")
            if chips:
                st.button("Clear all", key="cd_chip_clear_all", on_click=state.reset_filters)
