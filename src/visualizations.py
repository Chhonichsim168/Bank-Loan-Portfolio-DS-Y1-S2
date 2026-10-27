"""
visualizations.py
==================
Bank Loan Portfolio Analytics — Visualization Module

Generates all charts used in the report and dashboard. Every chart has a clear
title and labeled axes. Functions return a matplotlib Figure so callers (Streamlit,
report generator, notebooks) can render or save it as needed.
"""

from __future__ import annotations

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd
import seaborn as sns

sns.set_theme(style="whitegrid", palette="deep")
BANK_PALETTE = ["#0B3D91", "#1F6FEB", "#2FA84F", "#F2A900", "#D62839", "#6C5CE7"]
plt.rcParams.update({
    "figure.facecolor": "white",
    "axes.edgecolor": "#333333",
    "axes.titleweight": "bold",
    "axes.titlesize": 13,
    "axes.labelsize": 11,
    "font.family": "DejaVu Sans",
})


def _finish(fig, tight=True):
    if tight:
        fig.tight_layout()
    return fig


# 1. BAR CHART -------------------------------------------------------------------------
def chart_approval_rate_by_employment(df: pd.DataFrame):
    g = df.groupby("employment_status", observed=True)["approved"].mean().sort_values(ascending=False) * 100
    fig, ax = plt.subplots(figsize=(7, 4.5))
    bars = ax.bar(g.index.str.replace("_", " ").str.title(), g.values, color=BANK_PALETTE[:len(g)])
    ax.bar_label(bars, fmt="%.1f%%", padding=3)
    ax.set_title("Loan Approval Rate by Employment Status")
    ax.set_xlabel("Employment Status")
    ax.set_ylabel("Approval Rate (%)")
    ax.set_ylim(0, max(g.values) * 1.2)
    return _finish(fig)


# 2. LINE CHART --------------------------------------------------------------------------
def chart_approval_rate_by_income_decile(df: pd.DataFrame):
    d = df.copy()
    d["income_decile"] = pd.qcut(d["total_income"], 10, labels=False, duplicates="drop") + 1
    g = d.groupby("income_decile", observed=True)["approved"].mean() * 100
    fig, ax = plt.subplots(figsize=(7.5, 4.5))
    ax.plot(g.index, g.values, marker="o", linewidth=2.5, color=BANK_PALETTE[1])
    ax.set_title("Approval Rate Trend Across Income Deciles")
    ax.set_xlabel("Total Household Income Decile (1 = Lowest, 10 = Highest)")
    ax.set_ylabel("Approval Rate (%)")
    ax.set_xticks(range(1, g.index.max() + 1))
    return _finish(fig)


# 3. HISTOGRAM ----------------------------------------------------------------------------
def chart_income_distribution(df: pd.DataFrame):
    fig, ax = plt.subplots(figsize=(7.5, 4.5))
    ax.hist(df["total_income"], bins=40, color=BANK_PALETTE[0], edgecolor="white")
    ax.axvline(df["total_income"].median(), color=BANK_PALETTE[4], linestyle="--", linewidth=2,
               label=f"Median = {df['total_income'].median():,.0f}")
    ax.set_title("Distribution of Total Household Income")
    ax.set_xlabel("Total Income (Applicant + Co-applicant, monthly)")
    ax.set_ylabel("Number of Applicants")
    ax.legend()
    return _finish(fig)


# 4. PIE CHART -----------------------------------------------------------------------------
def chart_risk_level_share(df: pd.DataFrame):
    g = df["risk_level"].value_counts().reindex(["Low", "Medium", "High"]).dropna()
    fig, ax = plt.subplots(figsize=(6, 6))
    colors = [BANK_PALETTE[2], BANK_PALETTE[3], BANK_PALETTE[4]]
    ax.pie(g.values, labels=g.index, autopct="%1.1f%%", startangle=90,
           colors=colors[:len(g)], wedgeprops={"edgecolor": "white", "linewidth": 1.5})
    ax.set_title("Portfolio Share by Risk Level")
    ax.axis("equal")
    return _finish(fig)


# 5. SCATTER PLOT --------------------------------------------------------------------------
def chart_income_vs_loan_scatter(df: pd.DataFrame):
    fig, ax = plt.subplots(figsize=(7.5, 5))
    colors = df["approved"].map({1: BANK_PALETTE[2], 0: BANK_PALETTE[4]})
    ax.scatter(df["total_income"], df["loan_amount"], c=colors, alpha=0.5, s=22, edgecolor="none")
    ax.set_title("Loan Amount vs. Total Income (colored by approval outcome)")
    ax.set_xlabel("Total Income (monthly)")
    ax.set_ylabel("Loan Amount")
    handles = [plt.Line2D([0], [0], marker="o", color="w", markerfacecolor=BANK_PALETTE[2], label="Approved", markersize=8),
               plt.Line2D([0], [0], marker="o", color="w", markerfacecolor=BANK_PALETTE[4], label="Rejected", markersize=8)]
    ax.legend(handles=handles)
    return _finish(fig)


# 6. BOX PLOT ------------------------------------------------------------------------------
def chart_dti_boxplot_by_approval(df: pd.DataFrame):
    fig, ax = plt.subplots(figsize=(6.5, 5))
    data = [df.loc[df["approved"] == 1, "debt_to_income_ratio"],
            df.loc[df["approved"] == 0, "debt_to_income_ratio"]]
    bp = ax.boxplot(data, labels=["Approved", "Rejected"], patch_artist=True, widths=0.5)
    for patch, color in zip(bp["boxes"], [BANK_PALETTE[2], BANK_PALETTE[4]]):
        patch.set_facecolor(color)
        patch.set_alpha(0.6)
    ax.set_title("Debt-to-Income Ratio by Approval Outcome")
    ax.set_xlabel("Approval Outcome")
    ax.set_ylabel("Debt-to-Income Ratio")
    ax.yaxis.set_major_formatter(mticker.PercentFormatter(xmax=1.0))
    return _finish(fig)


# 7. HEATMAP (bonus — correlation) ----------------------------------------------------------
def chart_correlation_heatmap(df: pd.DataFrame):
    cols = ["applicant_income", "coapplicant_income", "loan_amount", "loan_term_months",
            "credit_history", "total_income", "loan_to_income_ratio", "estimated_emi",
            "debt_to_income_ratio", "approved"]
    corr = df[cols].corr(numeric_only=True)
    fig, ax = plt.subplots(figsize=(9, 7))
    sns.heatmap(corr, annot=True, fmt=".2f", cmap="RdBu_r", center=0, ax=ax,
                cbar_kws={"label": "Pearson correlation"}, square=True)
    ax.set_title("Correlation Matrix — Key Loan & Applicant Variables")
    return _finish(fig)


# 8. STACKED BAR (bonus) -------------------------------------------------------------------
def chart_property_area_outcomes(df: pd.DataFrame):
    ct = pd.crosstab(df["property_area"], df["approved"], normalize="index") * 100
    ct = ct.rename(columns={0: "Rejected", 1: "Approved"})
    fig, ax = plt.subplots(figsize=(7, 4.5))
    ct.plot(kind="bar", stacked=True, ax=ax, color=[BANK_PALETTE[4], BANK_PALETTE[2]])
    ax.set_title("Approval vs. Rejection Rate by Property Area")
    ax.set_xlabel("Property Area")
    ax.set_ylabel("Share of Applications (%)")
    ax.legend(title="Outcome")
    plt.setp(ax.get_xticklabels(), rotation=0)
    return _finish(fig)


ALL_CHARTS = {
    "approval_rate_by_employment": chart_approval_rate_by_employment,
    "approval_rate_by_income_decile": chart_approval_rate_by_income_decile,
    "income_distribution": chart_income_distribution,
    "risk_level_share": chart_risk_level_share,
    "income_vs_loan_scatter": chart_income_vs_loan_scatter,
    "dti_boxplot_by_approval": chart_dti_boxplot_by_approval,
    "correlation_heatmap": chart_correlation_heatmap,
    "property_area_outcomes": chart_property_area_outcomes,
}


def save_all_charts(df: pd.DataFrame, out_dir: str = "reports/figures") -> list[str]:
    """Render every chart and save as PNG. Returns list of saved file paths."""
    from pathlib import Path
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    saved = []
    for name, fn in ALL_CHARTS.items():
        fig = fn(df)
        path = f"{out_dir}/{name}.png"
        fig.savefig(path, dpi=150, bbox_inches="tight")
        plt.close(fig)
        saved.append(path)
    return saved


if __name__ == "__main__":
    import sys
    sys.path.insert(0, ".")
    from src.data_pipeline import run_pipeline
    clean_df, _ = run_pipeline("data/loan_data.csv")
    paths = save_all_charts(clean_df)
    print("Saved charts:")
    for p in paths:
        print(" -", p)
