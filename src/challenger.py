"""
challenger.py
=============
Champion / challenger comparison. The registered model (champion) is compared with simpler or
differently-weighted variants on the SAME out-of-fold folds, so the numbers are like for like.
Nothing is switched automatically: a challenger that looks better is a prompt for a human decision
(and a new model version), not a deployment.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import StratifiedKFold

from src.risk_model import (CATEGORICAL_FEATURES, IMPUTED_FLAGS, NUMERIC_FEATURES, TARGET, HistoricalEnsemble,
                            expected_calibration_error)

VARIANTS = {
    "Logistic only (calibrated)": (1.0, 0.0),
    "Gradient boosting only (calibrated)": (0.0, 1.0),
    "50 / 50 blend (calibrated)": (0.5, 0.5),
}


def _metrics(y: np.ndarray, p: np.ndarray, label: str) -> dict:
    return {"model": label, "AUC": float(roc_auc_score(y, p)), "Brier": float(np.mean((p - y) ** 2)),
            "Calibration error": expected_calibration_error(y, p)}


def _usable(book: pd.DataFrame) -> pd.DataFrame:
    flags = [c for c in IMPUTED_FLAGS if c in book.columns]
    return book.loc[~book[flags].any(axis=1)].reset_index(drop=True) if flags else book.reset_index(drop=True)


def compare(book: pd.DataFrame, champion, variants: dict | None = None) -> pd.DataFrame:
    """Rows: the champion first, then each challenger. Lower Brier / calibration error and higher AUC is better."""
    work = _usable(book)
    X = work[NUMERIC_FEATURES + CATEGORICAL_FEATURES]
    y = work[TARGET].astype(int).values
    rows = [_metrics(y, np.asarray(champion.oof_proba), f"Champion {champion.model_version} (75/25 blend)")]
    for label, (wl, wb) in (variants or VARIANTS).items():
        oof = np.zeros(len(X))
        for tr, te in StratifiedKFold(n_splits=5, shuffle=True, random_state=42).split(X, y):
            m = HistoricalEnsemble(wl, wb).fit(X.iloc[tr], pd.Series(y[tr], index=X.index[tr]))
            oof[te] = m.predict_proba(X.iloc[te])[:, 1]
        rows.append(_metrics(y, oof, label))
    df = pd.DataFrame(rows)
    best = df.loc[df["AUC"].idxmax(), "model"]
    df["Verdict"] = ["Best AUC" if m == best else "" for m in df["model"]]
    return df
