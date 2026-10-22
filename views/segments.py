"""Segments — where approval and risk concentrate across the book."""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src import analytics as an
from views._filters import filter_bar
from src import ui
from src.security import to_safe_csv
from src.state import RISK_ORDER, ctx

DIMENSIONS = {
    "Property area": "property_area",
    "Employment": "employment_status",
    "Income band": "income_bracket",
    "Loan size": "loan_size_category",
    "Risk tier": "risk_level",
    "Credit history": "credit_history",
}
# Time dimensions, offered only when the book carries application dates.
DATE_DIMENSIONS = {
    "Application quarter": "application_quarter",
    "Application year": "application_year",
    "Day of the week": "application_weekday",
}


def dimensions(df: pd.DataFrame) -> dict:
    return {**DIMENSIONS, **{k: v for k, v in DATE_DIMENSIONS.items() if v in df.columns}}


def render() -> None:
    c = ctx()
    view, book = c.view, c.book

    ui.page_header(
        "Segments",
        "Cut the book by dimension to see where approval rates and exposure diverge "
        "from the portfolio average.",
        eyebrow="Portfolio",
    )
    filter_bar(c)

    if len(view) < 10:
        ui.note("Too few applications in this selection to segment meaningfully.",
                title="Not enough data", tone="warn")
        return

    _single_dimension(view, book)
    _grid(view)
    _ranked_table(view, book)


# -----------------------------------------------------------------------------------------
def _single_dimension(view: pd.DataFrame, book: pd.DataFrame) -> None:
    ui.section("Approval rate by dimension")

    dims = dimensions(view)
    choice = ui.choice("Break down by", list(dims.keys()),
                       default="Property area", key="seg_dim")
    col = dims[choice]

    g = an.approval_rate_by(view, col)
    baseline = float(view["approved"].mean())

    labels = [_label(col, i) for i in g.index]
    rates = g["approval_rate_pct"].values
    colors = [ui.LOW if r >= baseline * 100 else ui.HIGH for r in rates]

    left, right = st.columns([1.4, 1], gap="medium")

    with left:
        fig = go.Figure()
        fig.add_bar(
            y=labels, x=rates, orientation="h",
            marker_color=colors, marker_line_width=0, opacity=0.9,
            text=[f"{r:.1f}%" for r in rates], textposition="outside",
            textfont=dict(size=11.5, color=ui.INK),
            hovertemplate="%{y}<br>Approved %{x:.1f}%<extra></extra>",
        )
        fig.add_vline(
            x=baseline * 100, line_color=ui.INK_SOFT, line_width=1.2, line_dash="dot",
            annotation_text="selection average", annotation_position="top",
            annotation_font=dict(size=10.5, color=ui.INK_SOFT),
        )
        fig.update_layout(
            xaxis=dict(title="Approval rate", ticksuffix="%",
                       range=[0, max(rates.max() * 1.22, 10)]),
            yaxis=dict(title="", autorange="reversed"),
            bargap=0.42,
        )
        ui.chart(fig, height=max(230, 62 * len(g)))

    with right:
        table = pd.DataFrame({
            "Segment": labels,
            "Applications": g["applications"].values,
            "Approval rate": rates,
            "Avg loan": g["avg_loan_amount"].values,
        })
        ui.table(
            ui.style_table(table, pct_cols=["Approval rate"], money_cols=["Avg loan"]), hide_index=True,
        )

    spread = rates.max() - rates.min()
    top, bottom = labels[int(np.argmax(rates))], labels[int(np.argmin(rates))]
    tone = "warn" if spread > 25 else "info"
    ui.note(
        f"<b>{top}</b> approves {spread:.0f} points above <b>{bottom}</b> on this cut. "
        "A gap this size is worth separating into two questions before acting on it: is the "
        "underlying credit genuinely different, or is the segment harder to verify and "
        "therefore slower to approve? The first is risk. The second is process friction, and "
        "it is a fair-lending exposure.",
        tone=tone,
    )


def _label(col: str, value) -> str:
    if col == "credit_history":
        return "History on file" if value == 1 else "No history"
    return str(value).replace("_", "-").title()


# -----------------------------------------------------------------------------------------
def _grid(view: pd.DataFrame) -> None:
    ui.section("Two-way grid",
               "Approval rate at every intersection of property area and employment.")

    pt = an.pivot_area_vs_employment(view)
    if pt.empty:
        return

    x = [c.replace("_", "-").title() for c in pt.columns]
    y = [str(i).title() for i in pt.index]

    fig = go.Figure(go.Heatmap(
        z=pt.values, x=x, y=y,
        colorscale=[[0, "#FBF2F2"], [0.4, "#F4E7DA"], [0.7, "#D9EAE1"], [1, ui.LOW]],
        zmin=0, zmax=100,
        text=[[f"{v:.0f}%" if pd.notna(v) else "—" for v in row] for row in pt.values],
        texttemplate="%{text}", textfont=dict(size=13, color=ui.INK),
        hovertemplate="%{y} · %{x}<br>Approved %{z:.1f}%<extra></extra>",
        colorbar=dict(title=dict(text="Approval", font=dict(size=11)),
                      ticksuffix="%", thickness=10, len=0.75, outlinewidth=0),
        xgap=3, ygap=3,
    ))
    fig.update_layout(xaxis=dict(title="", side="top"), yaxis=dict(title="", autorange="reversed"))
    ui.chart(fig, height=250)

    flat = pt.stack()
    if len(flat) >= 2:
        worst_idx = flat.idxmin()
        best_idx = flat.idxmax()
        ui.note(
            f"The weakest cell is <b>{str(worst_idx[0]).title()} · "
            f"{str(worst_idx[1]).replace('_', '-')}</b> at {flat.min():.0f}%, against "
            f"<b>{str(best_idx[0]).title()} · {str(best_idx[1]).replace('_', '-')}</b> at "
            f"{flat.max():.0f}%. Cells with few applications will swing; check the counts in "
            "the ranked table below before treating a cell as a finding."
        )


# -----------------------------------------------------------------------------------------
def _ranked_table(view: pd.DataFrame, book: pd.DataFrame) -> None:
    ui.section("Every segment, ranked",
               "All area × employment × risk combinations, sorted by how far they sit from "
               "the book average.")

    baseline = float(book["approved"].mean())
    g = (
        view.groupby(["property_area", "employment_status", "risk_level"], observed=True)
        .agg(applications=("approved", "count"),
             approval_rate=("approved", "mean"),
             avg_dti=("debt_to_income_ratio", "mean"),
             exposure=("loan_amount", "sum"))
        .reset_index()
    )
    min_n = st.slider("Minimum applications per segment", 5, 120, 20, step=5,
                      help="Small segments produce unstable rates. Raise this to see only "
                           "segments large enough to act on.")
    g = g[g["applications"] >= min_n].copy()

    if g.empty:
        ui.note("No segment reaches that size in the current selection.", tone="warn")
        return

    g["gap"] = g["approval_rate"] - baseline
    g = g.sort_values("gap")

    table = pd.DataFrame({
        "Area": g["property_area"].str.title(),
        "Employment": g["employment_status"].str.replace("_", "-"),
        "Risk": g["risk_level"],
        "Applications": g["applications"],
        "Approval rate": g["approval_rate"] * 100,
        "Gap to book": g["gap"] * 100,
        "Avg DTI": g["avg_dti"] * 100,
        "Exposure": g["exposure"],
    })

    ui.table(
        ui.gradient(table.style
        .format({"Approval rate": "{:.1f}%", "Gap to book": "{:+.1f}pp",
                 "Avg DTI": "{:.1f}%", "Exposure": "${:,.0f}", "Applications": "{:,}"})
        , cmap="RdYlGn", subset=["Gap to book"], vmin=-40, vmax=40), hide_index=True, height=380,
    )

    st.download_button(
        "Download segment table (CSV)",
        to_safe_csv(table),
        file_name="credit_desk_segments.csv",
        mime="text/csv",
    )
