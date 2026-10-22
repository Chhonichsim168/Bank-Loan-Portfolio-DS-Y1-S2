"""Portfolio overview — the ten-second answer to 'how is the book doing?'."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src import decisioning as dec
from views._filters import filter_bar
from src import ui
from src.state import RISK_ORDER, ctx


def render() -> None:
    c = ctx()
    view, book = c.view, c.book
    s = c.stats()

    ui.page_header(
        "Portfolio overview",
        "Approval performance, exposure and risk concentration across the current book.",
        eyebrow="Portfolio",
    )
    filter_bar(c)

    if view.empty:
        ui.note(
            "No applications match the current filters. Clear one of them in the left rail "
            "to bring the book back into view.",
            title="Nothing to show",
            tone="warn",
        )
        return

    _kpis(s, view, c.baseline_label)
    st.markdown("")
    if c.has_dates:
        _trend(c)

    left, right = st.columns([1.55, 1], gap="medium")
    with left:
        _risk_tier_chart(view)
    with right:
        _concentration(view)

    _affordability(view, c.policy)
    _queue_preview(view, c.policy)


# -----------------------------------------------------------------------------------------
def _kpis(s: dict, view: pd.DataFrame, baseline: str = "book average") -> None:
    cols = st.columns(5, gap="small")

    with cols[0]:
        ui.kpi(
            "Applications",
            ui.count(s["applications"]["value"]),
            delta=(f"{s['applications']['delta'] / s['applications']['baseline'] * 100:+.0f}%"
                   if baseline == "previous period" and s["applications"]["baseline"] else None),
            delta_dir="flat",
            foot=f"{ui.money(s['exposure']['value'])} requested",
        )

    with cols[1]:
        d = s["approval_rate"]["delta"]
        ui.kpi(
            "Approval rate",
            ui.pct(s["approval_rate"]["value"]),
            delta=ui.pp(d) if abs(d) > 1e-9 else None,
            delta_dir=ui.delta_dir(d, good_when_rising=True),
            foot=f"{baseline} {ui.pct(s['approval_rate']['baseline'])}",
        )

    with cols[2]:
        d = s["avg_dti"]["delta"]
        value = s["avg_dti"]["value"]
        label, _ = ui.band_label(value, ui.DTI_BANDS)
        ui.kpi(
            "Average debt-to-income",
            ui.pct(value),
            delta=ui.pp(d) if abs(d) > 1e-9 else None,
            delta_dir=ui.delta_dir(d, good_when_rising=False),
            rail=ui.band_rail(value, ui.DTI_BANDS, caption=f"<span>{label}</span>"),
        )

    with cols[3]:
        d = s["high_risk_share"]["delta"]
        ui.kpi(
            "High-risk share",
            ui.pct(s["high_risk_share"]["value"]),
            delta=ui.pp(d) if abs(d) > 1e-9 else None,
            delta_dir=ui.delta_dir(d, good_when_rising=False),
            foot=f"{int((view['risk_level'] == 'High').sum()):,} applications",
        )

    with cols[4]:
        d = s["avg_loan"]["delta"]
        ui.kpi(
            "Average loan",
            ui.money(s["avg_loan"]["value"]),
            delta=(f"{d / s['avg_loan']['baseline'] * 100:+.1f}%"
                   if s["avg_loan"]["baseline"] and abs(d) > 1e-9 else None),
            delta_dir="flat",
            foot=f"median {ui.money(view['loan_amount'].median())}",
        )


# -----------------------------------------------------------------------------------------
def monthly_trend(df: pd.DataFrame) -> pd.DataFrame:
    """Applications, approval rate, requested exposure and high-risk share per month."""
    g = df.groupby("application_month").agg(
        applications=("approved", "size"), approval_rate=("approved", "mean"),
        exposure=("loan_amount", "sum"), high_risk=("risk_level", lambda r: (r == "High").mean()))
    return g.reset_index().sort_values("application_month")


def _trend(c) -> None:
    t = monthly_trend(c.timeline)
    if len(t) < 2:
        return
    sub = ("Every month in the book, with the selected period shaded. Bars are applications "
           "(left axis); the line is the approval rate (right axis).")
    ui.section("Monthly trend", sub)
    fig = go.Figure()
    fig.add_bar(x=t["application_month"], y=t["applications"], name="Applications",
                marker_color="#A9D4CD",
                hovertemplate="%{x}<br>%{y:,} applications<extra></extra>")
    fig.add_scatter(x=t["application_month"], y=t["approval_rate"], name="Approval rate", yaxis="y2",
                    mode="lines+markers", line=dict(width=2.5, color=ui.BRAND_DEEP),
                    hovertemplate="%{x}<br>%{y:.1%} approved<extra></extra>")
    if c.period is not None:
        x0, x1 = f"{c.period[0]:%Y-%m}", f"{c.period[1]:%Y-%m}"
        months = list(t["application_month"])
        if x0 in months or x1 in months:
            i0 = months.index(x0) if x0 in months else 0
            i1 = months.index(x1) if x1 in months else len(months) - 1
            fig.add_vrect(x0=i0 - 0.5, x1=i1 + 0.5, fillcolor=ui.BRAND, opacity=0.08, line_width=0)
    fig.update_layout(
        yaxis=dict(title="Applications", rangemode="tozero"),
        yaxis2=dict(title="Approval rate", overlaying="y", side="right", tickformat=".0%",
                    range=[0, 1], tickmode="array", tickvals=[0, 0.25, 0.5, 0.75, 1], showgrid=False),
        xaxis=dict(type="category", tickangle=-45),
        legend=dict(orientation="h", y=1.12, x=0), bargap=0.25, margin=dict(t=30, b=10))
    ui.chart(fig, height=320)

    # Year-on-year line: same months, this year vs last year, when both exist.
    last = c.timeline["application_date"].max()
    ytd = c.timeline[c.timeline["application_year"] == last.year]
    prior = c.timeline[(c.timeline["application_year"] == last.year - 1)
                       & (c.timeline["application_date"].dt.dayofyear <= last.dayofyear)]
    if len(ytd) and len(prior):
        ch = len(ytd) / len(prior) - 1
        ar = ytd["approved"].mean() - prior["approved"].mean()
        st.caption(f"Year to date ({last:%d %b %Y}): {len(ytd):,} applications, {ch:+.0%} on the same "
                   f"period last year; approval rate {ytd['approved'].mean():.1%} ({ar * 100:+.1f} pp).")


# -----------------------------------------------------------------------------------------
def _risk_tier_chart(view: pd.DataFrame) -> None:
    ui.section("Approval and exposure by risk tier",
               "Volume tells you where the book is. Approval rate tells you how it is being "
               "treated. Read them together.")

    g = (
        view.groupby("risk_level", observed=True)
        .agg(applications=("approved", "count"),
             approval_rate=("approved", "mean"),
             exposure=("loan_amount", "sum"))
        .reindex(RISK_ORDER)
        .dropna(subset=["applications"])
    )

    fig = go.Figure()
    fig.add_bar(
        x=g.index, y=g["exposure"],
        marker_color=[ui.RISK_COLORS[i] for i in g.index],
        marker_line_width=0, opacity=0.85, name="Exposure",
        hovertemplate="%{x} risk<br>Exposure %{y:$,.0f}<extra></extra>",
    )
    fig.add_scatter(
        x=g.index, y=g["approval_rate"] * 100, yaxis="y2", mode="lines+markers+text",
        line=dict(color=ui.INK, width=2), marker=dict(size=9, color=ui.INK),
        text=[f"{v * 100:.0f}%" for v in g["approval_rate"]],
        textposition="top center", textfont=dict(size=11.5, color=ui.INK),
        name="Approval rate",
        hovertemplate="%{x} risk<br>Approved %{y:.1f}%<extra></extra>",
    )
    fig.update_layout(
        yaxis=dict(title="Requested exposure", tickprefix="$", tickformat="~s"),
        yaxis2=dict(title="Approval rate", overlaying="y", side="right",
                    range=[0, 108], ticksuffix="%", showgrid=False),
        xaxis=dict(title=""),
        legend=dict(orientation="h", y=1.08, x=0),
        bargap=0.55,
    )
    ui.chart(fig, height=340)

    if len(g) >= 2:
        best, worst = g["approval_rate"].idxmax(), g["approval_rate"].idxmin()
        spread = (g.loc[best, "approval_rate"] - g.loc[worst, "approval_rate"]) * 100
        ui.note(
            f"The tiers separate cleanly: <b>{best}</b> risk approves at "
            f"<b>{g.loc[best, 'approval_rate'] * 100:.0f}%</b> against "
            f"<b>{g.loc[worst, 'approval_rate'] * 100:.0f}%</b> for <b>{worst}</b>, a "
            f"{spread:.0f} point spread. A tier that did not separate would mean the scoring "
            "rule was picking up noise rather than credit quality."
        )


def _concentration(view: pd.DataFrame) -> None:
    ui.section("Where the book sits")

    rc = view["risk_level"].value_counts().reindex(RISK_ORDER).dropna()
    fig = go.Figure(go.Pie(
        labels=rc.index, values=rc.values, hole=0.62, sort=False,
        marker=dict(colors=[ui.RISK_COLORS[i] for i in rc.index],
                    line=dict(color=ui.SURFACE, width=2)),
        textinfo="label+percent", textposition="outside",
        hovertemplate="%{label} risk<br>%{value:,} applications<extra></extra>",
    ))
    fig.update_layout(
        showlegend=False, margin=dict(l=10, r=10, t=10, b=10),
        annotations=[dict(
            text=f"<b>{len(view):,}</b><br><span style='font-size:11px;color:{ui.INK_SOFT}'>applications</span>",
            x=0.5, y=0.5, showarrow=False, font=dict(size=20, color=ui.INK),
        )],
    )
    ui.chart(fig, height=248)

    top = (
        view.groupby(["property_area", "employment_status"], observed=True)
        .agg(n=("approved", "count"), rate=("approved", "mean"))
        .sort_values("n", ascending=False)
        .head(3)
    )
    rows = "".join(
        f'<div style="display:flex;justify-content:space-between;padding:0.3rem 0;'
        f'border-bottom:1px solid {ui.BORDER};font-size:0.845rem;">'
        f'<span>{a.title()} · {e.replace("_", "-")}</span>'
        f'<span style="color:{ui.INK_SOFT};">{int(r["n"]):,} at {r["rate"] * 100:.0f}%</span></div>'
        for (a, e), r in top.iterrows()
    )
    st.markdown(
        f'<div style="font-size:0.79rem;color:{ui.INK_SOFT};font-weight:500;'
        f'margin-bottom:0.2rem;">Largest segments</div>{rows}',
        unsafe_allow_html=True,
    )


# -----------------------------------------------------------------------------------------
def _affordability(view: pd.DataFrame, policy: dec.Policy) -> None:
    ui.section("Affordability distribution",
               "Where applicants fall against the debt-to-income policy bands.")

    fig = go.Figure()
    for tier in RISK_ORDER:
        sub = view[view["risk_level"] == tier]
        if sub.empty:
            continue
        fig.add_histogram(
            x=sub["debt_to_income_ratio"].clip(upper=0.8) * 100,
            name=f"{tier} risk", nbinsx=44, opacity=0.78,
            marker_color=ui.RISK_COLORS[tier], marker_line_width=0,
            hovertemplate=f"{tier} risk<br>DTI %{{x:.0f}}%<br>%{{y}} applications<extra></extra>",
        )
    fig.add_vline(
        x=policy.max_dti * 100, line_color=ui.INK, line_width=1.5, line_dash="dot",
        annotation_text=f"policy cap {policy.max_dti * 100:.0f}%",
        annotation_position="top right",
        annotation_font=dict(size=11, color=ui.INK),
    )
    fig.update_layout(
        barmode="stack",
        xaxis=dict(title="Debt-to-income ratio", ticksuffix="%"),
        yaxis=dict(title="Applications"),
    )
    ui.chart(fig, height=300)

    over = float((view["debt_to_income_ratio"] > policy.max_dti).mean())
    ui.note(
        f"<b>{ui.pct(over)}</b> of this selection sits above the {policy.max_dti * 100:.0f}% "
        "debt-to-income cap. High-risk applications cluster in the right tail, which is the "
        "shape you want — if the tiers overlapped evenly across the range, the risk rule "
        "would not be doing any work. Adjust the cap on the Policy and cut-offs page to see "
        "how much volume moves."
    )


def _queue_preview(view: pd.DataFrame, policy: dec.Policy) -> None:
    ui.section("Needs attention",
               "Applications breaching current policy, heaviest exposure first.")

    flagged = dec.exceptions(view, policy, limit=8)
    if flagged.empty:
        ui.note("Nothing in this selection breaches policy.", title="Queue is clear")
        return

    display = flagged.assign(
        loan_amount=flagged["loan_amount"].map(lambda v: f"${v:,.0f}"),
        debt_to_income_ratio=flagged["debt_to_income_ratio"].map(lambda v: f"{v * 100:.0f}%"),
        total_income=flagged["total_income"].map(lambda v: f"${v:,.0f}"),
    )[["loan_amount", "total_income", "debt_to_income_ratio", "risk_level",
       "breach_count", "breach_reason"]]
    display.columns = ["Loan", "Monthly income", "DTI", "Risk", "Breaches", "Why it is flagged"]

    ui.table(display, hide_index=True)

    total_flagged = int((~dec.apply_policy(view, policy)["policy_pass"]).sum())
    st.caption(
        f"Showing the 8 largest of {total_flagged:,} flagged applications. "
        "The full queue and the rules behind it are on Policy and cut-offs."
    )
