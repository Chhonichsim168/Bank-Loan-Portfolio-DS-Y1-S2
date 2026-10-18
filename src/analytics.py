"""
analytics.py
============
Bank Loan Portfolio Analytics — Analytics Module

Provides reusable functions covering:
    - Filtering, sorting, grouping, aggregation, pivot tables / crosstabs
    - Descriptive & inferential statistics (mean, median, mode, std, var, correlation)
    - The 5 core Analytical Questions defined for this project (see README)

Every function returns a plain pandas object (DataFrame/Series) so it can be reused
identically by the Streamlit app, the report generator, or a Jupyter notebook.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


# --------------------------------------------------------------------------------------
# DESCRIPTIVE / SUMMARY STATISTICS
# --------------------------------------------------------------------------------------
def numeric_summary_stats(df: pd.DataFrame, columns: list[str] | None = None) -> pd.DataFrame:
    """Mean, median, mode, min, max, std, variance for the given numeric columns."""
    columns = columns or df.select_dtypes(include=np.number).columns.tolist()
    rows = []
    for col in columns:
        s = df[col].dropna()
        mode_val = s.mode()
        rows.append({
            "field": col,
            "mean": round(s.mean(), 3),
            "median": round(s.median(), 3),
            "mode": round(mode_val.iloc[0], 3) if not mode_val.empty else np.nan,
            "min": round(s.min(), 3),
            "max": round(s.max(), 3),
            "std_dev": round(s.std(), 3),
            "variance": round(s.var(), 3),
        })
    return pd.DataFrame(rows).set_index("field")


def correlation_matrix(df: pd.DataFrame, columns: list[str] | None = None) -> pd.DataFrame:
    """Pearson correlation matrix for numeric fields."""
    columns = columns or df.select_dtypes(include=np.number).columns.tolist()
    return df[columns].corr(numeric_only=True).round(3)


# --------------------------------------------------------------------------------------
# FILTER / SORT
# --------------------------------------------------------------------------------------
def filter_portfolio(
    df: pd.DataFrame,
    employment_status: list[str] | None = None,
    property_area: list[str] | None = None,
    risk_level: list[str] | None = None,
    approved: int | None = None,
    min_income: float | None = None,
    max_income: float | None = None,
    min_loan: float | None = None,
    max_loan: float | None = None,
) -> pd.DataFrame:
    """Flexible multi-condition filter over the loan portfolio."""
    out = df.copy()
    if employment_status:
        out = out[out["employment_status"].isin(employment_status)]
    if property_area:
        out = out[out["property_area"].isin(property_area)]
    if risk_level:
        out = out[out["risk_level"].isin(risk_level)]
    if approved is not None:
        out = out[out["approved"] == approved]
    if min_income is not None:
        out = out[out["total_income"] >= min_income]
    if max_income is not None:
        out = out[out["total_income"] <= max_income]
    if min_loan is not None:
        out = out[out["loan_amount"] >= min_loan]
    if max_loan is not None:
        out = out[out["loan_amount"] <= max_loan]
    return out


def top_n_by(df: pd.DataFrame, column: str, n: int = 10, ascending: bool = False) -> pd.DataFrame:
    """Sort and return the top-N records by a given column."""
    return df.sort_values(by=column, ascending=ascending).head(n)


# --------------------------------------------------------------------------------------
# GROUPING / AGGREGATION / PIVOTS
# --------------------------------------------------------------------------------------
def approval_rate_by(df: pd.DataFrame, group_col: str) -> pd.DataFrame:
    """Approval rate (%), average loan amount, and applicant count by a categorical field."""
    g = df.groupby(group_col, observed=True).agg(
        applications=("approved", "count"),
        approvals=("approved", "sum"),
        avg_loan_amount=("loan_amount", "mean"),
        avg_income=("total_income", "mean"),
    )
    g["approval_rate_pct"] = (g["approvals"] / g["applications"] * 100).round(2)
    g["avg_loan_amount"] = g["avg_loan_amount"].round(0)
    g["avg_income"] = g["avg_income"].round(0)
    return g.sort_values("approval_rate_pct", ascending=False)


def risk_distribution(df: pd.DataFrame) -> pd.DataFrame:
    """Count and % share of applications across risk levels, split by approval outcome."""
    ct = pd.crosstab(df["risk_level"], df["approved"], margins=True, margins_name="Total")
    ct.columns = ["Rejected", "Approved", "Total"] if list(ct.columns) == [0, 1, "Total"] else ct.columns
    return ct


def pivot_area_vs_employment(df: pd.DataFrame, value: str = "approved", aggfunc: str = "mean") -> pd.DataFrame:
    """Pivot table: property_area (rows) x employment_status (cols) -> aggregated value."""
    pt = pd.pivot_table(
        df, index="property_area", columns="employment_status", values=value,
        aggfunc=aggfunc, observed=True,
    )
    if aggfunc == "mean" and value == "approved":
        pt = (pt * 100).round(2)  # express as approval rate %
    return pt


def credit_history_impact(df: pd.DataFrame) -> pd.DataFrame:
    """Approval outcomes segmented by credit history flag (0 = bad, 1 = good)."""
    return approval_rate_by(df, "credit_history")


def income_bracket_analysis(df: pd.DataFrame) -> pd.DataFrame:
    """Loan behaviour segmented by income bracket."""
    g = df.groupby("income_bracket", observed=True).agg(
        applicants=("applicant_income", "count"),
        avg_total_income=("total_income", "mean"),
        avg_loan_amount=("loan_amount", "mean"),
        avg_debt_to_income=("debt_to_income_ratio", "mean"),
        approval_rate_pct=("approved", lambda x: round(x.mean() * 100, 2)),
    ).round(2)
    return g


# --------------------------------------------------------------------------------------
# THE 5 CORE ANALYTICAL QUESTIONS (see README for full statement)
# --------------------------------------------------------------------------------------
def answer_q1_credit_history_effect(df: pd.DataFrame) -> pd.DataFrame:
    """Q1: How strongly does credit history influence loan approval?"""
    return credit_history_impact(df)


def answer_q2_income_vs_approval(df: pd.DataFrame) -> pd.DataFrame:
    """Q2: Does higher applicant income correlate with higher approval likelihood?"""
    return income_bracket_analysis(df)


def answer_q3_area_employment_patterns(df: pd.DataFrame) -> pd.DataFrame:
    """Q3: Do approval patterns differ across property area and employment type?"""
    return pivot_area_vs_employment(df)


def answer_q4_risk_segment_sizes(df: pd.DataFrame) -> pd.DataFrame:
    """Q4: What share of the portfolio falls into each risk segment, and how do they perform?"""
    g = df.groupby("risk_level", observed=True).agg(
        applicants=("approved", "count"),
        approval_rate_pct=("approved", lambda x: round(x.mean() * 100, 2)),
        avg_debt_to_income=("debt_to_income_ratio", "mean"),
    ).round(3)
    g["share_of_portfolio_pct"] = round(g["applicants"] / len(df) * 100, 2)
    return g


def answer_q5_dti_threshold_effect(df: pd.DataFrame) -> pd.DataFrame:
    """Q5: At what debt-to-income ratio does approval likelihood drop off sharply?"""
    bins = [-np.inf, 0.20, 0.30, 0.40, 0.50, np.inf]
    labels = ["<20%", "20-30%", "30-40%", "40-50%", "50%+"]
    df = df.copy()
    df["dti_band"] = pd.cut(df["debt_to_income_ratio"], bins=bins, labels=labels)
    g = df.groupby("dti_band", observed=True).agg(
        applicants=("approved", "count"),
        approval_rate_pct=("approved", lambda x: round(x.mean() * 100, 2)),
    )
    return g
