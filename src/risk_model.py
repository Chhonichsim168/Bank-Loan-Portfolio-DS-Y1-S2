"""Historical loan approval model for the Credit Desk application.

The model is deliberately built around every predictive field available in the new
loan_data.csv.  In particular, credit_score and late_payments_12m are now first-class
predictors; the previous version silently ignored both of them.

A soft ensemble blends a calibrated, interpretable logistic model with a non-linear
GradientBoosting model.  This lets the model learn interactions such as high loan burden
combined with weak credit history instead of assuming every relationship is linear.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, ClassifierMixin
from sklearn.compose import ColumnTransformer
from scipy.optimize import minimize
from scipy.special import expit
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import accuracy_score, confusion_matrix, precision_score, recall_score, roc_auc_score, roc_curve, f1_score
from sklearn.base import clone
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

TARGET = "approved"
CATEGORICAL_FEATURES = ["employment_status", "property_area"]
# Raw numeric fields from the new dataset + engineered historical/affordability fields.
# FIX (repayment term): the raw term is NOT scored directly any more (see NOT_SCORED). In the historical data short
# loans were rarely approved, so the model had learned "shorter term = much lower score" (120
# months scored ~11% vs 65% for 360 months, for the same customer) even when the instalment was
# well inside the DTI cap - and the sensitivity panel then nudged customers toward 30-year loans.
# The term still counts, correctly, through affordability: it sets the instalment
# (estimated_emi / debt_to_income_ratio), which can only lower the score as it rises.
NUMERIC_FEATURES = [
    "applicant_income", "coapplicant_income", "loan_amount", "loan_term_months",
    "credit_history", "dependents", "credit_score", "late_payments_12m",
    "total_income", "loan_to_income_ratio", "loan_to_annual_income", "estimated_emi",
    "debt_to_income_ratio", "household_size", "credit_score_band", "late_payment_rate",
    "credit_payment_stress", "income_per_dependent", "loan_burden_x_credit",
]
# Columns carried with every application (for the reference applicant, range checks and the
# instalment) but deliberately given no weight of their own by the model.
NOT_SCORED = ["loan_term_months"]
SCORED_NUMERIC = [c for c in NUMERIC_FEATURES if c not in NOT_SCORED]

# --------------------------------------------------------------------------------------
# Business-sense direction constraints.
# +1 -> a higher value must NEVER lower the approval probability
# -1 -> a higher value must NEVER raise the approval probability
# Without these, correlated fields (credit_history, credit_score, late payments) could
# steal each other's signal, so that MORE late payments or a LOWER score produced a HIGHER
# approval probability.
# --------------------------------------------------------------------------------------
MONOTONIC_DIRECTION = {
    "credit_score": +1, "credit_score_band": +1, "credit_history": +1,
    "late_payments_12m": -1, "late_payment_rate": -1, "credit_payment_stress": -1,
    "loan_burden_x_credit": -1, "debt_to_income_ratio": -1, "estimated_emi": -1,
    "loan_to_income_ratio": -1, "loan_to_annual_income": -1,
    # FIX: these were unconstrained. Historically the big loans were the 30-year ones, so the
    # model learned "bigger loan = higher approval" and used loan size as a hidden stand-in for
    # term: at the SAME monthly instalment a smaller 10-year loan scored lower than a bigger
    # 30-year one. A bigger loan can now never raise the score, and more income never lower it.
    "loan_amount": -1,
    "applicant_income": +1, "coapplicant_income": +1, "total_income": +1,
}
CATEGORY_DIRECTION = {"employment_status_unemployed": -1}
# Minimum standardized logistic weight for the two headline credit-behaviour fields.
# In this dataset `credit_history` is almost a summary of score + late payments, so an
# unconstrained fit lets it absorb their effect (leaving them ~0 or wrongly signed).
# A floor keeps them visibly influential: better score -> higher, more lates -> lower.
MIN_EFFECT = {"credit_score": 0.30, "late_payments_12m": 0.30}


def _direction_for(feature_name: str) -> int:
    name = feature_name.split("__", 1)[-1]
    return MONOTONIC_DIRECTION.get(name, CATEGORY_DIRECTION.get(name, 0))


class SignConstrainedLogistic(BaseEstimator, ClassifierMixin):
    """L2 logistic regression whose coefficients obey MONOTONIC_DIRECTION.

    Exposes coef_ / intercept_ / predict_proba so the reason-code utilities keep working.
    `directions` is a list aligned with the (already scaled) input columns.
    """
    def __init__(self, directions=None, C: float = 1.0, class_weight: str = "balanced", max_iter: int = 2000,
                 min_abs=None):
        self.directions = directions
        self.min_abs = min_abs
        self.C = C
        self.class_weight = class_weight
        self.max_iter = max_iter

    def fit(self, X, y):
        X = np.asarray(X, dtype=float)
        y = np.asarray(y, dtype=float)
        n, d = X.shape
        dirs = np.zeros(d) if self.directions is None else np.asarray(self.directions, dtype=float)
        if self.class_weight == "balanced":
            w1 = n / (2.0 * max(y.sum(), 1.0)); w0 = n / (2.0 * max((1 - y).sum(), 1.0))
            sw = np.where(y == 1, w1, w0)
        else:
            sw = np.ones(n)

        def objective(theta):
            w, b = theta[:-1], theta[-1]
            z = X @ w + b
            # numerically stable weighted log-loss
            loss = np.sum(sw * (np.logaddexp(0, z) - y * z)) + 0.5 * np.dot(w, w) / self.C
            r = sw * (expit(z) - y)
            grad = np.concatenate([X.T @ r + w / self.C, [r.sum()]])
            return loss, grad

        floor = np.zeros(d) if self.min_abs is None else np.asarray(self.min_abs, dtype=float)
        bounds = [(f, None) if s > 0 else (None, -f) if s < 0 else (None, None)
                  for s, f in zip(dirs, floor)] + [(None, None)]
        res = minimize(objective, np.zeros(d + 1), jac=True, method="L-BFGS-B", bounds=bounds,
                       options={"maxiter": self.max_iter})
        self.coef_ = res.x[:-1].reshape(1, -1)
        self.intercept_ = np.array([res.x[-1]])
        self.classes_ = np.array([0, 1])
        return self

    def decision_function(self, X):
        return np.asarray(X, dtype=float) @ self.coef_[0] + self.intercept_[0]

    def predict_proba(self, X):
        p = expit(self.decision_function(X))
        return np.column_stack([1 - p, p])

    def predict(self, X):
        return (self.predict_proba(X)[:, 1] >= 0.5).astype(int)


@dataclass
class ModelResult:
    pipeline: "HistoricalEnsemble"
    accuracy: float
    precision: float
    recall: float
    f1: float
    roc_auc: float
    confusion: np.ndarray
    fpr: np.ndarray
    tpr: np.ndarray
    feature_importance: pd.DataFrame
    validation_note: str = ""
    # --- added: reproducibility, calibration and stability evidence -------------------
    model_version: str = ""
    trained_at: str = ""
    train_rows: int = 0
    brier: float = float("nan")
    ece: float = float("nan")
    oof_proba: np.ndarray = field(default_factory=lambda: np.array([]))   # out-of-fold, whole book
    oof_y: np.ndarray = field(default_factory=lambda: np.array([]))
    cv_auc_mean: float = float("nan")
    cv_auc_std: float = float("nan")
    oot_auc: float | None = None
    oot_note: str = ""
    excluded_rows: int = 0


def _preprocessor() -> ColumnTransformer:
    return ColumnTransformer([
        ("num", StandardScaler(), SCORED_NUMERIC),
        ("cat", OneHotEncoder(drop="first", handle_unknown="ignore", sparse_output=False), CATEGORICAL_FEATURES),
    ], remainder="drop")


def _base_pipeline(model, boosting: bool = False) -> Pipeline:
    """Fitted pipelines need the direction vectors, which depend on the transformed columns."""
    pre = _preprocessor()
    return Pipeline([("preprocess", pre), ("model", model)])


def _transformed_names() -> list[str]:
    """Output column names of the preprocessor, without fitting on real data."""
    cats = {"employment_status": ["salaried", "self_employed", "unemployed"],
            "property_area": ["rural", "semiurban", "urban"]}
    names = list(SCORED_NUMERIC)
    for c in CATEGORICAL_FEATURES:
        names += [f"{c}_{v}" for v in cats[c][1:]]   # drop="first" removes the first category
    return names


def build_pipeline() -> "HistoricalEnsemble":
    """Build the same model structure used by training and scoring."""
    return HistoricalEnsemble()


RAW_FIELDS = ["applicant_income", "coapplicant_income", "loan_amount", "loan_term_months",
              "credit_history", "dependents", "credit_score", "late_payments_12m"]
DOMAIN_FIELDS = ["applicant_income", "coapplicant_income", "loan_amount", "loan_term_months",
                 "dependents", "credit_score", "late_payments_12m"]


class HistoricalEnsemble(BaseEstimator, ClassifierMixin):
    """Weighted soft-voting ensemble: 75% sign-constrained logistic + 25% monotonic gradient
    boosting, followed by a Platt calibration step fitted on out-of-fold scores.

    The calibration step matters: the logistic part is class-balanced, which shifts its
    probabilities away from real approval frequencies. After calibration a displayed 70% is
    meant to behave like 70% (see ``ece`` / ``brier`` on the ModelResult)."""
    def __init__(self, logistic_weight: float = 0.75, boosting_weight: float = 0.25,
                 calibrate: bool = True):
        self.logistic_weight = logistic_weight
        self.boosting_weight = boosting_weight
        self.calibrate = calibrate
        self.named_steps = {"preprocess": _preprocessor()}
        self.logistic = None
        self.boosting = None
        self._feature_names = None

    def fit(self, X: pd.DataFrame, y: pd.Series):
        X = pd.DataFrame(X)
        y = pd.Series(np.asarray(y).ravel(), index=X.index)   # sklearn helpers pass ndarrays
        directions = [_direction_for(n) for n in _transformed_names()]
        min_abs = [MIN_EFFECT.get(n, 0.0) for n in _transformed_names()]
        self.logistic = _base_pipeline(SignConstrainedLogistic(directions=directions, C=1.0, min_abs=min_abs))
        self.boosting = _base_pipeline(
            HistGradientBoostingClassifier(
                max_iter=300, learning_rate=0.03, max_depth=2, min_samples_leaf=20,
                l2_regularization=1.0, monotonic_cst=directions, random_state=42
            )
        )
        self.logistic.fit(X, y)
        self.boosting.fit(X, y)
        self.classes_ = np.array([0, 1])
        self.named_steps["preprocess"] = self.logistic.named_steps["preprocess"]
        self.named_steps["model"] = self.logistic.named_steps["model"]
        self._feature_names = list(self.logistic.named_steps["preprocess"].get_feature_names_out())

        # Reference applicant (typical profile) for Shapley reason codes, and the range of
        # values the model has actually seen, so out-of-range inputs can be flagged.
        ref = {c: float(np.median(X[c])) for c in RAW_FIELDS}
        ref["credit_history"] = int(X["credit_history"].mode().iloc[0])
        ref["dependents"] = int(round(ref["dependents"]))
        ref["loan_term_months"] = int(round(ref["loan_term_months"]))
        ref["credit_score"] = int(round(ref["credit_score"]))
        ref["late_payments_12m"] = int(round(ref["late_payments_12m"]))
        ref["employment_status"] = str(X["employment_status"].mode().iloc[0])
        ref["property_area"] = str(X["property_area"].mode().iloc[0])
        self.reference_ = ref
        self.domain_ = {c: (float(X[c].min()), float(X[c].max())) for c in DOMAIN_FIELDS}

        self.calibrator_ = None
        if self.calibrate:
            # Out-of-fold raw scores -> Platt scaling. Slope is kept positive so calibration
            # can never reverse the model's ranking or its monotonic constraints.
            raw_oof = np.zeros(len(X))
            cv = StratifiedKFold(n_splits=4, shuffle=True, random_state=7)
            for tr, te in cv.split(X, y):
                m = HistoricalEnsemble(self.logistic_weight, self.boosting_weight, calibrate=False)
                m.fit(X.iloc[tr], y.iloc[tr])
                raw_oof[te] = m._raw(X.iloc[te])
            z = _logit(raw_oof).reshape(-1, 1)
            lr = LogisticRegression(C=1e6, max_iter=1000).fit(z, y)
            a, b = float(max(lr.coef_[0, 0], 0.05)), float(lr.intercept_[0])
            self.calibrator_ = (a, b)
        return self

    def _raw(self, X: pd.DataFrame) -> np.ndarray:
        pl = self.logistic.predict_proba(X)[:, 1]
        pg = self.boosting.predict_proba(X)[:, 1]
        return self.logistic_weight * pl + self.boosting_weight * pg

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        p = self._raw(X)
        if getattr(self, "calibrator_", None) is not None:
            a, b = self.calibrator_
            p = expit(a * _logit(p) + b)
        return np.column_stack([1.0 - p, p])

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return (self.predict_proba(X)[:, 1] >= 0.5).astype(int)


def _logit(p, eps: float = 1e-6):
    p = np.clip(np.asarray(p, dtype=float), eps, 1 - eps)
    return np.log(p / (1 - p))


def expected_calibration_error(y, p, bins: int = 10) -> float:
    y, p = np.asarray(y, dtype=float), np.asarray(p, dtype=float)
    edges = np.linspace(0, 1, bins + 1)
    idx = np.clip(np.digitize(p, edges[1:-1]), 0, bins - 1)
    ece = 0.0
    for b in range(bins):
        m = idx == b
        if m.any():
            ece += m.mean() * abs(y[m].mean() - p[m].mean())
    return float(ece)


def model_version(df: pd.DataFrame) -> str:
    """Deterministic id: training data + features + constraints + hyper-parameters."""
    cols = [c for c in NUMERIC_FEATURES + CATEGORICAL_FEATURES + [TARGET] if c in df.columns]
    data_hash = hashlib.sha256(pd.util.hash_pandas_object(df[cols], index=False).values.tobytes()).hexdigest()
    spec = json.dumps({
        "data": data_hash, "numeric": NUMERIC_FEATURES, "categorical": CATEGORICAL_FEATURES,
        "monotonic": MONOTONIC_DIRECTION, "category_direction": CATEGORY_DIRECTION, "min_effect": MIN_EFFECT, "not_scored": NOT_SCORED,
        "hgb": [300, 0.03, 2, 20, 1.0, 42], "weights": [0.75, 0.25], "calibration": "platt-oof-4fold",
        "split": [0.25, 42],
    }, sort_keys=True)
    return "m-" + hashlib.sha256(spec.encode()).hexdigest()[:12]


def _tree_importance(pipe, X_test, y_test) -> np.ndarray:
    """HistGradientBoosting has no impurity importances; use permutation importance instead."""
    from sklearn.inspection import permutation_importance
    pre = pipe.boosting.named_steps["preprocess"]
    Z = pre.transform(X_test)
    r = permutation_importance(pipe.boosting.named_steps["model"], Z, y_test, n_repeats=5,
                               random_state=42, scoring="roc_auc")
    return np.clip(r.importances_mean, 0, None)


IMPUTED_FLAGS = ["credit_score_imputed", "late_payments_12m_imputed", "credit_history_imputed"]


def train_model(df: pd.DataFrame, test_size: float = 0.25, random_state: int = 42) -> ModelResult:
    required = NUMERIC_FEATURES + CATEGORICAL_FEATURES + [TARGET]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Dataset is missing model fields: {missing}")

    version = model_version(df)
    # A missing credit score / late-payment count / credit-history flag is NOT the same as a
    # typical one. Rows where the pipeline had to fill those in are kept in the book for
    # reporting but are not used to teach the model.
    flags = [c for c in IMPUTED_FLAGS if c in df.columns]
    keep = ~df[flags].any(axis=1) if flags else pd.Series(True, index=df.index)
    excluded = int((~keep).sum())
    work = df.loc[keep].reset_index(drop=True)

    X = work[NUMERIC_FEATURES + CATEGORICAL_FEATURES].copy()
    y = work[TARGET].astype(int)

    # --- time-aware validation when the extract carries an application date -----------
    date_col = next((c for c in ("application_date", "decision_date", "date") if c in work.columns), None)
    oot_auc, oot_note = None, ("No application date in this extract, so out-of-time validation is not "
                               "possible. The hold-out and cross-validation below measure fit, not "
                               "stability over time - obtain dated data before relying on this model.")
    if date_col is not None:
        dts = pd.to_datetime(work[date_col], errors="coerce")
        order = np.argsort(dts.fillna(dts.min()).values, kind="stable")
        cut = int(len(order) * (1 - test_size))
        tr_i, te_i = order[:cut], order[cut:]
        if y.iloc[tr_i].nunique() == 2 and y.iloc[te_i].nunique() == 2:
            m = build_pipeline().fit(X.iloc[tr_i], y.iloc[tr_i])
            oot_auc = float(roc_auc_score(y.iloc[te_i], m.predict_proba(X.iloc[te_i])[:, 1]))
            oot_note = (f"Trained on the oldest {cut:,} applications and tested on the newest "
                        f"{len(te_i):,} (by {date_col}).")

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=test_size, random_state=random_state, stratify=y
    )

    pipe = build_pipeline()
    pipe.fit(X_train, y_train)
    y_pred = pipe.predict(X_test)
    y_proba = pipe.predict_proba(X_test)[:, 1]
    fpr, tpr, _ = roc_curve(y_test, y_proba)

    # Out-of-fold scores for the whole book (every row scored by a model that never saw it):
    # used for choosing a cut-off, calibration and the score interval.
    oof = np.zeros(len(X))
    fold_auc = []
    for tr, te in StratifiedKFold(n_splits=5, shuffle=True, random_state=42).split(X, y):
        m = build_pipeline().fit(X.iloc[tr], y.iloc[tr])
        oof[te] = m.predict_proba(X.iloc[te])[:, 1]
        fold_auc.append(roc_auc_score(y.iloc[te], oof[te]))

    # Final model: fitted on the training split for the hold-out metrics above, but the model
    # that SCORES applicants is refitted on all usable rows (more data, same recipe).
    final = build_pipeline().fit(X, y)

    pre = final.named_steps["preprocess"]
    names = [n.split("__", 1)[-1] for n in pre.get_feature_names_out()]
    lr_coef = np.abs(final.logistic.named_steps["model"].coef_[0])
    tree_imp = _tree_importance(pipe, X_test, y_test)
    lr_norm = lr_coef / (lr_coef.sum() or 1)
    tree_norm = tree_imp / (tree_imp.sum() or 1)
    importance = 0.75 * lr_norm + 0.25 * tree_norm
    signed = final.logistic.named_steps["model"].coef_[0]
    fi = pd.DataFrame({"feature": names, "coefficient": signed, "importance": importance})
    fi["abs_coefficient"] = fi["coefficient"].abs()
    fi = fi.sort_values("importance", ascending=False).reset_index(drop=True)

    return ModelResult(
        pipeline=final,
        accuracy=round(accuracy_score(y_test, y_pred), 4),
        precision=round(precision_score(y_test, y_pred, zero_division=0), 4),
        recall=round(recall_score(y_test, y_pred, zero_division=0), 4),
        f1=round(f1_score(y_test, y_pred, zero_division=0), 4),
        roc_auc=round(roc_auc_score(y_test, y_proba), 4),
        confusion=confusion_matrix(y_test, y_pred),
        fpr=fpr, tpr=tpr,
        feature_importance=fi,
        validation_note=("25% stratified hold-out (metrics) + 5-fold out-of-fold scores; ensemble = 75% "
                         "logistic + 25% gradient boosting, Platt-calibrated on out-of-fold scores. "
                         "Scoring model is refitted on all usable rows."),
        model_version=version,
        trained_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        train_rows=int(len(work)),
        brier=float(np.mean((oof - y.values) ** 2)),
        ece=expected_calibration_error(y.values, oof),
        oof_proba=oof, oof_y=y.values,
        cv_auc_mean=float(np.mean(fold_auc)), cv_auc_std=float(np.std(fold_auc)),
        oot_auc=oot_auc, oot_note=oot_note, excluded_rows=excluded,
    )


def predict_single_applicant(pipeline: HistoricalEnsemble, applicant: dict) -> tuple[int, float]:
    from src.decisioning import enrich_application
    row = enrich_application(applicant)
    X = pd.DataFrame([row])[NUMERIC_FEATURES + CATEGORICAL_FEATURES]
    proba = float(pipeline.predict_proba(X)[0, 1])
    return int(proba >= 0.5), proba


if __name__ == "__main__":
    from src.data_pipeline import run_pipeline
    df, _ = run_pipeline("data/loan_data.csv")
    result = train_model(df)
    print(f"Accuracy : {result.accuracy}")
    print(f"Precision: {result.precision}")
    print(f"Recall   : {result.recall}")
    print(f"F1       : {result.f1}")
    print(f"ROC AUC  : {result.roc_auc}")
    print("\nTop features:")
    print(result.feature_importance.head(12))
