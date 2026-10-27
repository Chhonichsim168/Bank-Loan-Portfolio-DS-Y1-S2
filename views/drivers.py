"""Drivers — what actually moves an approval decision, ranked by evidence."""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src import analytics as an
from views._filters import filter_bar
from src import ui
from src.state import ctx

DRIVER_COLS = [
    "credit_history", "debt_to_income_ratio", "estimated_emi", "total_income",
    "applicant_income", "coapplicant_income", "loan_amount", "loan_to_annual_income",
    "loan_term_months", "dependents",
]

PRETTY = {
    "credit_history": "Credit history on file",
    "debt_to_income_ratio": "Debt-to-income ratio",
    "estimated_emi": "Monthly instalment",
    "total_income": "Total household income",
    "applicant_income": "Applicant income",
    "coapplicant_income": "Co-applicant income",
    "loan_amount": "Loan amount",
    "loan_to_annual_income": "Loan vs. annual income",
    "loan_term_months": "Repayment term",
    "dependents": "Dependents",
}


def render() -> None:
    c = ctx()
    view, book = c.view, c.book

    ui.page_header(
        "Approval drivers",
        "Which application characteristics actually move the decision, measured on this "
        "book rather than assumed.",
        eyebrow="Portfolio",
    )
    filter_bar(c)

    if len(view) < 30:
        ui.note("Too few applications for a stable correlation. Widen the filters.",
                title="Not enough data", tone="warn")
        return

    _ranked(view)
    if c.has_dates:
        _stability(c.timeline)
    _credit_history(view)
    _affordability_curve(view)
    _income_vs_affordability(view)
    _reference(view)


# -----------------------------------------------------------------------------------------
def driver_stability(df: pd.DataFrame) -> pd.DataFrame:
    """Correlation of each driver with approval, per calendar year: shows whether what moves
    the decision has changed over time (a policy change, a new credit officer, a new market)."""
    rows = {}
    for year, part in df.groupby("application_year"):
        if len(part) < 50:
            continue
        rows[str(year)] = {PRETTY[c]: part[c].astype(float).corr(part["approved"].astype(float))
                           for c in DRIVER_COLS if c in part and part[c].nunique() > 1}
    return pd.DataFrame(rows)


def _stability(timeline: pd.DataFrame) -> None:
    t = driver_stability(timeline)
    if t.shape[1] < 2:
        return
    ui.section("Have the drivers changed over time?",
               "Correlation with approval, calculated separately for each calendar year (years with "
               "at least 50 applications). A large change between years means the lending decision "
               "itself has shifted - worth asking why before trusting a model trained on all years.")
    t["Change"] = t.iloc[:, -1] - t.iloc[:, 0]
    t = t.reindex(t["Change"].abs().sort_values(ascending=False).index)
    t = t.rename_axis("Driver").reset_index()
    ui.table(t.style.format("{:+.2f}", subset=list(t.columns[1:])))


# -----------------------------------------------------------------------------------------
def _ranked(view: pd.DataFrame) -> None:
    ui.section("Ranked by strength of association",
               "Correlation between each field and the approval outcome across this selection.")

    if view["approved"].nunique() < 2:
        ui.note(
            "The outcome filter has left only one kind of decision in the selection, so "
            "there is nothing for these fields to correlate against. Set Outcome back to "
            "<b>All</b> in the left rail to see the drivers.",
            title="Both outcomes needed", tone="warn",
        )
        return

    cols = [c for c in DRIVER_COLS if c in view.columns]
    corr = view[cols + ["approved"]].corr(numeric_only=True)["approved"].drop("approved")
    corr = corr.dropna()
    if corr.empty:
        ui.note("Every field is constant across this selection — nothing to rank.",
                tone="warn")
        return
    corr = corr.reindex(corr.abs().sort_values(ascending=False).index)

    labels = [PRETTY.get(i, i) for i in corr.index]
    colors = [ui.LOW if v >= 0 else ui.HIGH for v in corr.values]

    fig = go.Figure(go.Bar(
        y=labels, x=corr.values, orientation="h",
        marker_color=colors, marker_line_width=0, opacity=0.9,
        text=[f"{v:+.2f}" for v in corr.values], textposition="outside",
        textfont=dict(size=11.5, color=ui.INK),
        hovertemplate="%{y}<br>r = %{x:.3f}<extra></extra>",
    ))
    fig.add_vline(x=0, line_color=ui.BORDER_STRONG, line_width=1)
    fig.update_layout(
        xaxis=dict(title="Correlation with approval", range=[-0.85, 0.85], zeroline=False),
        yaxis=dict(title="", autorange="reversed"),
        bargap=0.35,
    )
    ui.chart(fig, height=max(300, 38 * len(corr)))

    top = corr.abs().idxmax()
    ui.note(
        f"<b>{PRETTY.get(top, top)}</b> carries the strongest single association "
        f"(r = {corr[top]:+.2f}). Note that raw income sits well below the affordability "
        "ratios: what the book rewards is not earning more, it is owing less relative to "
        "what you earn. That distinction is what makes a debt-to-income cap a more "
        "defensible policy instrument than an income floor."
    )


# -----------------------------------------------------------------------------------------
def _credit_history(view: pd.DataFrame) -> None:
    ui.section("Credit history", "The largest single gap in the book.")

    r = an.credit_history_impact(view)
    if len(r) < 2:
        return

    good = float(r.loc[1, "approval_rate_pct"]) if 1 in r.index else np.nan
    bad = float(r.loc[0, "approval_rate_pct"]) if 0 in r.index else np.nan

    cols = st.columns([1, 1, 2.1], gap="medium")
    with cols[0]:
        ui.kpi("History on file", f"{good:.1f}%",
               foot=f"{int(r.loc[1, 'applications']):,} applications" if 1 in r.index else None)
    with cols[1]:
        ui.kpi("No history", f"{bad:.1f}%",
               delta=f"{bad - good:+.1f}pp", delta_dir="down",
               foot=f"{int(r.loc[0, 'applications']):,} applications" if 0 in r.index else None)
    with cols[2]:
        sub = view[view["credit_history"] == 0]
        strong = sub[(sub["debt_to_income_ratio"] < 0.30) &
                     (sub["employment_status"] != "unemployed")]
        rate = float(strong["approved"].mean()) * 100 if len(strong) else 0
        ui.kpi(
            "No history, but affordable and employed", f"{rate:.1f}%",
            foot=f"{len(strong):,} applications that a manual-review path would catch",
        )

    ui.note(
        f"The gap is <b>{good - bad:.0f} percentage points</b> — wider than every other "
        f"factor combined. That makes credit history the strongest pre-screening signal "
        f"available. It also makes it the one most likely to over-reject: within the "
        f"no-history group there are <b>{len(strong):,}</b> applicants who are employed and "
        f"comfortably inside the affordability bands. Routing those to manual review rather "
        f"than automatic decline is where a thin-file policy earns its keep.",
        title="Reading this",
    )


# -----------------------------------------------------------------------------------------
def _affordability_curve(view: pd.DataFrame) -> None:
    ui.section("The affordability curve",
               "Approval rate against debt-to-income, and where it gives way.")

    bins = [-np.inf, 0.10, 0.20, 0.30, 0.40, 0.50, 0.60, np.inf]
    labels = ["<10%", "10-20%", "20-30%", "30-40%", "40-50%", "50-60%", "60%+"]
    tmp = view.copy()
    tmp["band"] = pd.cut(tmp["debt_to_income_ratio"], bins=bins, labels=labels)
    g = (
        tmp.groupby("band", observed=True)
        .agg(applications=("approved", "count"), rate=("approved", "mean"))
        .reindex(labels).dropna(subset=["applications"])
    )

    # The bars sit on the base axis and the line on the overlay axis, so the line is always drawn
    # ON TOP of the bars (it used to be hidden behind them). Bars are lighter and capped at about
    # two-thirds of the height so the line and its labels stay clear above them.
    fig = go.Figure()
    fig.add_bar(
        x=g.index, y=g["applications"], name="Applications (right axis)",
        marker_color="#CBD5E1", opacity=0.55, marker_line_width=0,
        hovertemplate="%{x}<br>%{y:,} applications<extra></extra>",
    )
    fig.add_scatter(
        x=g.index, y=g["rate"] * 100, mode="lines+markers+text", name="Approval rate (left axis)",
        yaxis="y2",
        line=dict(color=ui.BRAND_DEEP, width=4), marker=dict(size=12, color=ui.BRAND_DEEP,
                                                             line=dict(color="#FFFFFF", width=2)),
        text=[f"<b>{v * 100:.0f}%</b>" for v in g["rate"]], textposition="top center",
        textfont=dict(size=13, color=ui.BRAND_DEEP),
        hovertemplate="%{x}<br>Approved %{y:.1f}%<extra></extra>",
    )
    fig.update_layout(
        yaxis=dict(title="Applications", side="right", showgrid=False,
                   range=[0, float(g["applications"].max()) * 1.55]),
        yaxis2=dict(title="Approval rate", ticksuffix="%", range=[0, 115], overlaying="y", side="left",
                    tickmode="array", tickvals=[0, 25, 50, 75, 100]),
        xaxis=dict(title="Debt-to-income band"),
        legend=dict(orientation="h", y=1.1, x=0),
    )
    ui.chart(fig, height=340)

    rates = g["rate"] * 100
    drops = rates.diff()
    if drops.notna().any():
        cliff = drops.idxmin()
        ui.note(
            f"The sharpest single fall lands at the <b>{cliff}</b> band "
            f"({drops.min():.0f} points against the band below it). That is the natural "
            "place to put a cut-off: it is where the book's own history says affordability "
            "stops being manageable. Setting the cap materially tighter than this mostly "
            "declines business the book shows it could have written."
        )


# -----------------------------------------------------------------------------------------
def _income_vs_affordability(view: pd.DataFrame) -> None:
    ui.section("Income alone is not the signal")

    sample = view.sample(min(1200, len(view)), random_state=7)
    fig = go.Figure()
    for outcome, label in [(1, "Approved"), (0, "Declined")]:
        sub = sample[sample["approved"] == outcome]
        fig.add_scatter(
            x=sub["total_income"], y=sub["loan_amount"], mode="markers", name=label,
            marker=dict(size=5.5, opacity=0.48,
                        color=ui.LOW if outcome == 1 else ui.HIGH,
                        line=dict(width=0)),
            hovertemplate=f"{label}<br>Income $%{{x:,.0f}}/mo<br>Loan $%{{y:,.0f}}<extra></extra>",
        )
    for mult, dash in [(3.5, "dot")]:
        xs = np.linspace(sample["total_income"].min(), sample["total_income"].max(), 50)
        fig.add_scatter(
            x=xs, y=xs * 12 * mult, mode="lines", name=f"{mult}x annual income (affordability line)",
            line=dict(color=ui.INK, width=3, dash="dash"), hoverinfo="skip",
        )
    fig.update_layout(
        xaxis=dict(title="Total monthly household income", tickprefix="$", tickformat="~s"),
        yaxis=dict(title="Loan amount requested", tickprefix="$", tickformat="~s",
                   range=[0, float(sample["loan_amount"].quantile(0.995)) * 1.15]),
    )
    ui.chart(fig, height=390)

    ui.note(
        "Approvals and declines overlap heavily on income alone — there is no income level "
        "above which applications are simply approved. What separates them is position "
        "relative to the affordability line: applications sitting well above 3.5x annual "
        "income are declined across the whole income range, including at the top of it."
    )


def _reference(view: pd.DataFrame) -> None:
    with st.expander("Reference statistics"):
        cols = ["applicant_income", "coapplicant_income", "total_income", "loan_amount",
                "estimated_emi", "debt_to_income_ratio", "loan_to_annual_income"]
        cols = [c for c in cols if c in view.columns]
        stats = an.numeric_summary_stats(view, cols)
        stats.index = [PRETTY.get(i, i) for i in stats.index]
        ui.table(stats, hide_index=False)

        skew = view["total_income"].mean() / max(view["total_income"].median(), 1)
        st.caption(
            f"Mean household income sits {skew:.2f}x its median, confirming a right-skewed "
            "distribution. This is why the pipeline imputes with the median rather than the "
            "mean: a handful of very high earners would otherwise drag every filled value "
            "upward."
        )
