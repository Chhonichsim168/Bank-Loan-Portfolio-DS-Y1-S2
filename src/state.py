"""
state.py
========
Credit Desk — application state.

Loading, caching and the filter context, in one place. Pages call `ctx()` and get
everything they need: the full book, the current selection, the trained model and a
description of which filters are active.

Keeping this separate means a page never re-runs the pipeline or retrains a model, and
never has to know how either happens.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

from src import analytics as an
from src import decisioning as dec
from src import app_store, policy_store, registry
from src.data_pipeline import DATE_COL, PipelineReport, has_dates, run_pipeline
from src.risk_model import ModelResult

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA = ROOT / "data" / "loan_data.csv"

RISK_ORDER = ["Low", "Medium", "High"]

# -----------------------------------------------------------------------------------------
# PERIOD FILTER. Presets are anchored on the LATEST application in the book (not on today),
# so an extract that ends last month still shows a full "latest month".
# -----------------------------------------------------------------------------------------
PERIODS = ["All time", "Latest month", "Last 3 months", "Last 6 months", "Last 12 months",
           "Year to date", "Previous calendar year", "Custom range"]


def period_bounds(book: pd.DataFrame, preset: str, custom: tuple | None = None) -> tuple | None:
    """(start, end) Timestamps, both inclusive, for a preset; None for All time / no dates."""
    if preset == "All time" or not has_dates(book):
        return None
    last = book[DATE_COL].max().normalize()
    first = book[DATE_COL].min().normalize()
    if preset == "Latest month":
        start = last.replace(day=1)
    elif preset in ("Last 3 months", "Last 6 months", "Last 12 months"):
        n = int(preset.split()[1])
        start = (last.replace(day=1) - pd.DateOffset(months=n - 1))
    elif preset == "Year to date":
        start = last.replace(month=1, day=1)
    elif preset == "Previous calendar year":
        start = pd.Timestamp(year=last.year - 1, month=1, day=1)
        last = pd.Timestamp(year=last.year - 1, month=12, day=31)
    elif preset == "Custom range" and custom and len(custom) == 2 and all(custom):
        start, last = pd.Timestamp(custom[0]), pd.Timestamp(custom[1])
    else:
        return None
    if preset != "Custom range":
        start = max(start, first)
    return start, last


def previous_bounds(bounds: tuple) -> tuple:
    """The window of equal length immediately before ``bounds``."""
    start, end = bounds
    # Whole calendar months (e.g. "Last 3 months" = Jul-Sep) -> the same number of months before.
    if start.day == 1 and (end + pd.Timedelta(days=1)).day == 1:
        months = (end.year - start.year) * 12 + end.month - start.month + 1
        return start - pd.DateOffset(months=months), start - pd.Timedelta(days=1)
    length = end - start + pd.Timedelta(days=1)
    return start - length, start - pd.Timedelta(days=1)


def in_period(df: pd.DataFrame, bounds: tuple | None) -> pd.DataFrame:
    if bounds is None or not has_dates(df):
        return df
    d = df[DATE_COL].dt.normalize()
    return df[(d >= bounds[0]) & (d <= bounds[1])]


def fmt_bounds(bounds: tuple | None) -> str:
    if bounds is None:
        return "all dates"
    return f"{bounds[0]:%d %b %Y} – {bounds[1]:%d %b %Y}"



# =========================================================================================
# CACHED LOADERS
# =========================================================================================
@st.cache_data(show_spinner=False)
def load_book(version: str) -> tuple[pd.DataFrame, PipelineReport]:
    """The applications in the SQLite database, cleaned. ``version`` changes whenever a record is
    added or removed, so every chart and KPI follows the database automatically."""
    return run_pipeline(app_store.load_frame(), drop_invalid=True)


@st.cache_data(show_spinner=False)
def load_raw(version: str) -> pd.DataFrame:
    return app_store.load_frame()


@st.cache_resource(show_spinner="Updating the model for the current data (about 15 seconds the first time)...")
def fit_model(_book: pd.DataFrame, fingerprint: str) -> ModelResult:
    """The registered model for exactly this data (trained and saved on first use, then loaded
    from data/models). `fingerprint` keys the cache; the frame is passed unhashed."""
    return registry.load_or_train(_book)


def honest_probabilities(_book: pd.DataFrame, fingerprint: str) -> np.ndarray:
    """Out-of-fold scores for the usable rows of the book, from the registered model - used
    wherever a cut-off is chosen. Rows excluded from training (imputed credit fields) are
    scored by the final model, which never used them."""
    m = fit_model(_book, fingerprint)
    usable = _usable_mask(_book)
    out = np.empty(len(_book))
    out[usable.values] = m.oof_proba
    if (~usable).any():
        Xe = dec.enrich_frame(_book.loc[~usable])
        out[(~usable).values] = m.pipeline.predict_proba(Xe[dec.NUMERIC_FEATURES + dec.CATEGORICAL_FEATURES])[:, 1]
    return out


def _usable_mask(book: pd.DataFrame) -> pd.Series:
    flags = [c for c in ("credit_score_imputed", "late_payments_12m_imputed", "credit_history_imputed")
             if c in book.columns]
    return ~book[flags].any(axis=1) if flags else pd.Series(True, index=book.index)


def fingerprint_of(df: pd.DataFrame) -> str:
    """Content hash of the book: any added, removed or changed record gives a new key."""
    h = pd.util.hash_pandas_object(df, index=False).values.tobytes()
    return f"{len(df)}:{df.shape[1]}:{hashlib.sha256(h).hexdigest()[:16]}"


# =========================================================================================
# CONTEXT
# =========================================================================================
@dataclass
class Context:
    book: pd.DataFrame           # every application, after cleaning
    view: pd.DataFrame           # the current filtered selection
    report: PipelineReport
    model: ModelResult
    period: tuple | None         # (start, end) of the period filter, None = all dates
    prev_view: pd.DataFrame | None  # same filters, the equal-length period just before
    timeline: pd.DataFrame       # every filter EXCEPT the period, for trend charts
    chips: list[tuple[str, str]]  # active filters, for the context bar
    source_name: str
    policy: dec.Policy
    settings: policy_store.Settings
    policy_version: int
    model_version: str
    cutoff: float

    @property
    def filtered(self) -> bool:
        return len(self.view) != len(self.book)

    @property
    def has_dates(self) -> bool:
        return has_dates(self.book)

    @property
    def baseline_label(self) -> str:
        """What the KPI deltas are measured against."""
        return "previous period" if self._use_prev else "book average"

    @property
    def _use_prev(self) -> bool:
        return self.prev_view is not None and len(self.prev_view) > 0

    def stats(self) -> dict:
        """Headline metrics. With a period selected, deltas are against the previous period of
        the same length (e.g. this quarter vs last quarter); otherwise against the whole book."""
        return dec.compare_to_book(self.view, self.prev_view if self._use_prev else self.book)


def _ss(key: str, default):
    if key not in st.session_state:
        st.session_state[key] = default
    return st.session_state[key]


def init() -> None:
    """Seed per-session UI defaults (filters only). Policy, cut-off and the data source are NOT
    session state: they live in the database (src/policy_store.py) and are shared by every user."""
    _ss("f_area", [])
    _ss("f_emp", [])
    _ss("f_risk", [])
    _ss("f_outcome", "All")
    _ss("f_period", "All time")
    # The filter bar is drawn only on the pages that use it. Writing each value back keeps it
    # when the user visits a page without the bar (Streamlit otherwise forgets a widget's value
    # on a run where the widget is not drawn).
    for k in ("f_area", "f_emp", "f_risk", "f_outcome", "f_period", "f_custom"):
        if k in st.session_state:
            st.session_state[k] = st.session_state[k]


def current_policy() -> dec.Policy:
    """The approved hard-policy rules, as every user sees them."""
    return policy_store.active().settings.policy()


def current_cutoff() -> float:
    return policy_store.active().settings.cutoff


def ctx() -> Context:
    """The single accessor every page uses."""
    book, report = load_book(app_store.version())
    fp = fingerprint_of(book)
    model = fit_model(book, fp)

    active = policy_store.active()
    areas = st.session_state.get("f_area", [])
    emp = st.session_state.get("f_emp", [])
    risk = st.session_state.get("f_risk", [])
    outcome = st.session_state.get("f_outcome", "All")

    approved = {"Approved only": 1, "Declined only": 0}.get(outcome)

    filtered = an.filter_portfolio(
        book,
        employment_status=emp or None,
        property_area=areas or None,
        risk_level=risk or None,
        approved=approved,
    )
    preset = st.session_state.get("f_period", "All time")
    bounds = period_bounds(book, preset, st.session_state.get("f_custom"))
    view = in_period(filtered, bounds)
    prev_view = in_period(filtered, previous_bounds(bounds)) if bounds else None

    chips: list[tuple[str, str]] = []
    if areas:
        chips.append(("area", ", ".join(a.title() for a in areas)))
    if emp:
        chips.append(("employment", ", ".join(e.replace("_", "-") for e in emp)))
    if risk:
        chips.append(("risk", ", ".join(risk)))
    if approved is not None:
        chips.append(("outcome", outcome.replace(" only", "")))
    if bounds is not None:
        chips.append(("period", fmt_bounds(bounds)))

    return Context(
        book=book,
        view=view,
        report=report,
        model=model,
        period=bounds,
        prev_view=prev_view,
        timeline=filtered,
        chips=chips,
        source_name=f"SQLite database ({app_store.source_name()})",
        policy=active.settings.policy(),
        settings=active.settings,
        policy_version=active.version,
        model_version=model.model_version,
        cutoff=active.settings.cutoff,
    )


def reset_filters() -> None:
    st.session_state["f_area"] = []
    st.session_state["f_emp"] = []
    st.session_state["f_risk"] = []
    st.session_state["f_outcome"] = "All"
    st.session_state["f_period"] = "All time"
    st.session_state.pop("f_custom", None)
