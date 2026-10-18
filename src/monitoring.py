"""
monitoring.py
=============
Post-deployment model monitoring: population drift (PSI), score drift, back-testing against
real outcomes, and a retrain trigger. Pure pandas/numpy - runs in a notebook or a batch job.

PSI (population stability index) thresholds follow common practice:
    < 0.10  stable        0.10 - 0.25  watch        > 0.25  shifted - investigate / retrain
"""

from __future__ import annotations

import numpy as np
import pandas as pd

PSI_WATCH, PSI_ACT = 0.10, 0.25
MONITORED_NUMERIC = ["applicant_income", "coapplicant_income", "loan_amount", "loan_term_months",
                     "credit_score", "late_payments_12m", "dependents", "debt_to_income_ratio",
                     "loan_to_annual_income"]
MONITORED_CATEGORICAL = ["employment_status", "property_area", "credit_history"]
EPS = 1e-4


def reference_profile(df: pd.DataFrame, scores: np.ndarray | None = None) -> dict:
    """Bin the training data once so later populations can be compared against it."""
    prof: dict = {"numeric": {}, "categorical": {}, "score": None, "n": int(len(df))}
    for col in MONITORED_NUMERIC:
        if col not in df.columns:
            continue
        x = pd.to_numeric(df[col], errors="coerce").dropna()
        edges = np.unique(np.quantile(x, np.linspace(0, 1, 11)))
        if len(edges) < 3:                       # near-constant column
            edges = np.unique(np.array([x.min() - 1, x.median(), x.max() + 1]))
        edges[0], edges[-1] = -np.inf, np.inf
        counts, _ = np.histogram(x, bins=edges)
        prof["numeric"][col] = {"edges": edges.tolist(), "props": (counts / max(counts.sum(), 1)).tolist()}
    for col in MONITORED_CATEGORICAL:
        if col in df.columns:
            prof["categorical"][col] = df[col].astype(str).value_counts(normalize=True).to_dict()
    if scores is not None and len(scores):
        edges = np.linspace(0, 1, 11)
        edges[0], edges[-1] = -np.inf, np.inf
        counts, _ = np.histogram(scores, bins=edges)
        prof["score"] = {"edges": edges.tolist(), "props": (counts / counts.sum()).tolist()}
    return prof


def psi(expected: np.ndarray, actual: np.ndarray) -> float:
    e = np.clip(np.asarray(expected, dtype=float), EPS, None)
    a = np.clip(np.asarray(actual, dtype=float), EPS, None)
    e, a = e / e.sum(), a / a.sum()
    return float(np.sum((a - e) * np.log(a / e)))


def status(value: float) -> str:
    return "Stable" if value < PSI_WATCH else "Watch" if value < PSI_ACT else "Shifted"


def drift_table(profile: dict, new: pd.DataFrame, scores: np.ndarray | None = None) -> pd.DataFrame:
    """PSI of each monitored field (and the score) for ``new`` against the training profile."""
    rows = []
    for col, ref in (profile.get("numeric") or {}).items():
        if col in new.columns and new[col].notna().any():
            x = pd.to_numeric(new[col], errors="coerce").dropna()
            counts, _ = np.histogram(x, bins=np.array(ref["edges"]))
            rows.append((col, psi(ref["props"], counts / max(counts.sum(), 1))))
    for col, ref in (profile.get("categorical") or {}).items():
        if col in new.columns:
            cats = sorted(set(ref) | set(new[col].astype(str)))
            e = np.array([ref.get(c, 0.0) for c in cats])
            a = new[col].astype(str).value_counts(normalize=True)
            rows.append((col, psi(e, np.array([a.get(c, 0.0) for c in cats]))))
    if scores is not None and profile.get("score") and len(scores):
        ref = profile["score"]
        counts, _ = np.histogram(scores, bins=np.array(ref["edges"]))
        rows.append(("model score", psi(ref["props"], counts / counts.sum())))
    out = pd.DataFrame(rows, columns=["Field", "PSI"])
    out["Status"] = out["PSI"].map(status)
    return out.sort_values("PSI", ascending=False).reset_index(drop=True)


def retrain_recommended(table: pd.DataFrame, min_rows: int = 200, n_rows: int = 0) -> tuple[bool, str]:
    """A simple, explainable trigger: any field or the score shifted, on enough volume."""
    if n_rows < min_rows:
        return False, f"Only {n_rows} recent applications - need at least {min_rows} for a reliable drift read."
    shifted = table[table["Status"] == "Shifted"]
    if len(shifted):
        return True, "Shifted: " + ", ".join(shifted["Field"]) + ". Review and consider retraining."
    return False, "No monitored field has shifted beyond the action threshold."


def _auc(y: np.ndarray, p: np.ndarray) -> float:
    from sklearn.metrics import roc_auc_score
    return float(roc_auc_score(y, p))


def ks_statistic(y: np.ndarray, p: np.ndarray) -> float:
    order = np.argsort(p)
    y = np.asarray(y)[order]
    pos, neg = max(y.sum(), 1), max((1 - y).sum(), 1)
    return float(np.max(np.abs(np.cumsum(y) / pos - np.cumsum(1 - y) / neg)))


def backtest(scores: pd.Series, outcomes: pd.Series, bins: int = 5) -> dict:
    """Compare scores with realised outcomes (1 = the good outcome the score predicts).

    Returns discrimination (AUC, Gini, KS), calibration (Brier, mean predicted vs observed)
    and a score-band table. Needs both outcomes present in the sample."""
    y = np.asarray(outcomes, dtype=int)
    p = np.asarray(scores, dtype=float)
    if len(y) < 30 or len(np.unique(y)) < 2:
        raise ValueError("Need at least 30 matched applications with both outcomes present.")
    auc = _auc(y, p)
    band = pd.qcut(pd.Series(p), q=min(bins, len(np.unique(p))), duplicates="drop")
    table = (pd.DataFrame({"band": band, "p": p, "y": y}).groupby("band", observed=True)
             .agg(applications=("y", "size"), mean_score=("p", "mean"), observed_rate=("y", "mean"))
             .reset_index())
    table["band"] = table["band"].astype(str)
    return {"n": int(len(y)), "auc": auc, "gini": 2 * auc - 1, "ks": ks_statistic(y, p),
            "brier": float(np.mean((p - y) ** 2)), "mean_score": float(p.mean()),
            "observed_rate": float(y.mean()), "table": table}
