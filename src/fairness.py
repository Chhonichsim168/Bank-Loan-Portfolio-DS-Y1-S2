"""
fairness.py
===========
Disparate-impact screening: approval rate by group and the **adverse impact ratio** (AIR) -
each group's approval rate divided by the highest group's rate. Below 0.80 is the common
"four-fifths" screening flag (a prompt to investigate, not a legal finding).

Limits, stated plainly: this dataset contains **no protected attributes** (sex, age,
ethnicity, religion, marital status). Direct testing is therefore impossible here. What this
module can do is (1) screen the *proxy-prone* fields the model does use - property area,
dependents, employment - and (2) automatically test any protected column that a future
extract does contain (see ``PROTECTED_CANDIDATES``).
"""

from __future__ import annotations

import pandas as pd

FOUR_FIFTHS = 0.80
MIN_GROUP = 30
PROTECTED_CANDIDATES = ["gender", "sex", "age", "age_band", "ethnicity", "race", "religion",
                        "marital_status", "nationality", "disability"]


def adverse_impact(df: pd.DataFrame, group: pd.Series, outcome: str | pd.Series = "approved",
                   min_group: int = MIN_GROUP) -> pd.DataFrame:
    y = df[outcome] if isinstance(outcome, str) else outcome
    t = pd.DataFrame({"group": group.astype(str).values, "y": pd.Series(y).astype(float).values})
    g = t.groupby("group").agg(applications=("y", "size"), approval_rate=("y", "mean")).reset_index()
    eligible = g[g["applications"] >= min_group]
    top = eligible["approval_rate"].max() if len(eligible) else float("nan")
    g["ratio_to_highest"] = g["approval_rate"] / top if top and top > 0 else float("nan")
    g["flag"] = g.apply(
        lambda r: "Too few cases" if r["applications"] < min_group
        else ("Below 0.80" if r["ratio_to_highest"] < FOUR_FIFTHS else "OK"), axis=1)
    return g.sort_values("approval_rate", ascending=False).reset_index(drop=True)


def groupings(df: pd.DataFrame) -> dict[str, pd.Series]:
    """Every grouping we can test on this extract: model inputs prone to acting as proxies,
    plus any protected column present."""
    out: dict[str, pd.Series] = {}
    if "property_area" in df:
        out["Property area (location proxy)"] = df["property_area"]
    if "employment_status" in df:
        out["Employment status"] = df["employment_status"]
    if "dependents" in df:
        out["Dependents (family-status proxy)"] = pd.cut(
            df["dependents"], [-1, 0, 2, 100], labels=["None", "1-2", "3 or more"])
    if "household_size" in df:
        out["Household size"] = pd.cut(df["household_size"], [0, 1, 3, 100], labels=["1", "2-3", "4 or more"])
    for col in PROTECTED_CANDIDATES:
        if col in df.columns:
            s = df[col]
            if pd.api.types.is_numeric_dtype(s) and s.nunique() > 8:
                s = pd.qcut(s, 4, duplicates="drop")
            out[f"{col} (protected attribute)"] = s
    return out


def screen(df: pd.DataFrame, outcome: str | pd.Series = "approved") -> pd.DataFrame:
    """One long table: every grouping x group, with AIR and flag."""
    frames = []
    for name, series in groupings(df).items():
        t = adverse_impact(df, series, outcome)
        t.insert(0, "dimension", name)
        frames.append(t)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def has_protected_attributes(df: pd.DataFrame) -> bool:
    return any(c in df.columns for c in PROTECTED_CANDIDATES)
