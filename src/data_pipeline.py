"""
data_pipeline.py
=================
Bank Loan Portfolio Analytics — Data Pipeline Module

Responsible for:
    1. Loading raw loan application data
    2. Structural inspection (shape, dtypes, columns)
    3. Missing value detection & handling
    4. Duplicate detection & removal
    5. Data validation (ranges, categories, invalid entries)
    6. Feature engineering (derived / calculated columns)

Author: Bank Loan Portfolio Analytics Team
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("data_pipeline")

# --------------------------------------------------------------------------------------
# Business constants (assumptions made explicit and documented — see README §Assumptions)
# --------------------------------------------------------------------------------------
ASSUMED_ANNUAL_INTEREST_RATE = 0.085   # 8.5% p.a., used only to derive an illustrative EMI

# FIX (zero income): a ratio over ZERO income is not "no burden" - it is unaffordable.
# Previously the code filled these ratios with 0, so an applicant with no income looked like
# the safest possible borrower (scored ~89% and passed the DTI/LTI caps). A zero-income ratio
# is now set to this large finite value: far beyond every cap, and still finite so the model's
# scaler accepts it. apply_policy() also adds an explicit "No income" breach.
NO_INCOME_RATIO = 99.0


def safe_ratio(numerator, income):
    """numerator / income, or NO_INCOME_RATIO when income is zero or negative.
    Works on scalars and on pandas Series."""
    if isinstance(income, pd.Series):
        inc = income.where(income > 0)
        return (numerator / inc).fillna(NO_INCOME_RATIO)
    income = float(income)
    return float(numerator) / income if income > 0 else NO_INCOME_RATIO

# Loan above this multiple of ANNUAL household income counts as an affordability stretch.
# 3.5x is the conventional retail-mortgage benchmark; change it here and the risk tiers,
# the policy defaults and the exceptions queue all move together.
LTI_HIGH_THRESHOLD = 3.5
VALID_EMPLOYMENT_STATUSES = {"salaried", "self_employed", "unemployed"}
VALID_PROPERTY_AREAS = {"urban", "semiurban", "rural"}
MIN_INCOME, MAX_INCOME = 0, 200_000          # sanity bounds for monthly income (USD)
MIN_LOAN, MAX_LOAN = 0, 5_000_000            # sanity bounds for loan principal (USD)
MIN_TERM, MAX_TERM = 12, 480                 # 1 year .. 40 years, in months
MAX_DEPENDENTS = 10
MIN_CREDIT_SCORE, MAX_CREDIT_SCORE = 300, 850
MAX_LATE_PAYMENTS_12M = 24

# --------------------------------------------------------------------------------------
# DATES. Every application carries the day it was received (``application_date``). The date
# is used to filter, trend and validate over time - it is NEVER a model input, so the model
# cannot learn "applications in month X get approved". Older extracts without the column still
# load; every date feature then simply hides itself.
# --------------------------------------------------------------------------------------
DATE_COL = "application_date"
MIN_APPLICATION_DATE = pd.Timestamp("2000-01-01")
LOCAL_TZ = "Asia/Phnom_Penh"          # the bank's local time zone for display and "today"


def today_local() -> pd.Timestamp:
    """Today's date in the bank's local time zone (UTC+7), as a tz-naive midnight Timestamp."""
    return pd.Timestamp.now(tz=LOCAL_TZ).normalize().tz_localize(None)


def to_local(ts, fmt: str = "%d/%m/%Y %H:%M"):
    """UTC ISO timestamps (as stored in the database) -> Phnom Penh local time strings.
    Records are kept in UTC so they sort and compare correctly; people read local time."""
    t = pd.to_datetime(ts, utc=True, errors="coerce")
    if isinstance(t, (pd.Series, pd.Index)):
        return pd.Series(t).dt.tz_convert(LOCAL_TZ).dt.strftime(fmt).fillna("")
    return "" if pd.isna(t) else t.tz_convert(LOCAL_TZ).strftime(fmt)


def days_since(ts) -> pd.Series:
    """Whole days elapsed since UTC ISO timestamps, measured now."""
    t = pd.to_datetime(pd.Series(ts), utc=True, errors="coerce")
    return ((pd.Timestamp.now(tz="UTC") - t).dt.total_seconds() // 86400).astype("Int64")


def parse_dates(values) -> pd.Series:
    """Parse application dates. ISO (2026-10-16) is the standard; day-first (16/10/2026), as
    written in Cambodia, is also accepted. Anything else becomes NaT and is reported."""
    s = pd.Series(values)
    if pd.api.types.is_datetime64_any_dtype(s):
        return s
    txt = s.astype("string").str.strip()
    iso = pd.to_datetime(txt, errors="coerce", format="%Y-%m-%d")
    dayfirst = pd.to_datetime(txt, errors="coerce", format="%d/%m/%Y")
    return iso.fillna(dayfirst)


def has_dates(df: pd.DataFrame) -> bool:
    return DATE_COL in df.columns and pd.api.types.is_datetime64_any_dtype(df[DATE_COL]) \
        and df[DATE_COL].notna().any()


def add_date_parts(df: pd.DataFrame) -> pd.DataFrame:
    """Derive month / quarter / year / weekday labels from ``application_date`` (in place)."""
    d = df[DATE_COL]
    df["application_month"] = d.dt.strftime("%Y-%m")
    df["application_quarter"] = d.dt.year.astype("Int64").astype(str) + "-Q" + d.dt.quarter.astype("Int64").astype(str)
    df["application_year"] = d.dt.year.astype("Int64")
    df["application_weekday"] = d.dt.day_name()
    return df

# Risk-tier rule (additive, maximum 10 points). The Data and governance page reads these
# constants, so the documentation cannot drift away from what the pipeline actually does.
RISK_SCORE_BAD_BELOW, RISK_SCORE_WEAK_BELOW = 580, 670   # credit score: +2 below 580, +1 below 670
RISK_LATE_SEVERE_AT, RISK_LATE_ANY_AT = 3, 1            # late payments (12m): +2 at 3+, +1 at 1-2
RISK_DTI_HIGH, RISK_DTI_MID = 0.45, 0.30                # debt-to-income: +2 above 45%, +1 above 30%
RISK_HIGH_MIN, RISK_MEDIUM_MIN = 6, 3                   # tier cut-offs on the 0-10 score
RISK_MAX_POINTS = 10


@dataclass
class PipelineReport:
    """Captures every decision the pipeline makes, for full transparency & audit trail."""
    rows_in: int = 0
    rows_out: int = 0
    missing_before: dict = field(default_factory=dict)
    missing_after: dict = field(default_factory=dict)
    duplicates_found: int = 0
    duplicates_dropped: int = 0
    invalid_rows_flagged: dict = field(default_factory=dict)
    invalid_rows_dropped: int = 0
    columns_added: list = field(default_factory=list)
    notes: list = field(default_factory=list)

    def log(self, msg: str) -> None:
        self.notes.append(msg)
        logger.info(msg)

    def summary(self) -> str:
        lines = [
            "=" * 72,
            "DATA PIPELINE REPORT — Bank Loan Portfolio Analytics",
            "=" * 72,
            f"Rows in                : {self.rows_in:,}",
            f"Rows out (final, clean): {self.rows_out:,}",
            f"Duplicate rows found   : {self.duplicates_found:,}",
            f"Duplicate rows dropped : {self.duplicates_dropped:,}",
            f"Invalid rows dropped   : {self.invalid_rows_dropped:,}",
            f"Columns added          : {', '.join(self.columns_added) if self.columns_added else 'None'}",
            "-" * 72,
            "Missing values BEFORE cleaning:",
        ]
        for k, v in self.missing_before.items():
            if v:
                lines.append(f"    {k:<22}: {v}")
        if not any(self.missing_before.values()):
            lines.append("    (none detected)")
        lines.append("Missing values AFTER cleaning:")
        for k, v in self.missing_after.items():
            if v:
                lines.append(f"    {k:<22}: {v}")
        if not any(self.missing_after.values()):
            lines.append("    (none remaining)")
        lines.append("-" * 72)
        lines.append("Notes / justifications:")
        for n in self.notes:
            lines.append(f"    - {n}")
        lines.append("=" * 72)
        return "\n".join(lines)


# --------------------------------------------------------------------------------------
# 1. LOAD
# --------------------------------------------------------------------------------------
def load_data(path: str | Path) -> pd.DataFrame:
    """Load the raw loan applications CSV into a DataFrame."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Dataset not found at: {path}")
    df = pd.read_csv(path)
    logger.info(f"Loaded {len(df):,} rows and {df.shape[1]} columns from {path.name}")
    return df


def inspect_data(df: pd.DataFrame) -> dict:
    """Return a dictionary of the standard Pandas inspection outputs (task requirement #5)."""
    buf_info = []
    df.info(buf=type("Buf", (), {"write": buf_info.append, "flush": lambda self: None})())
    return {
        "head": df.head(),
        "shape": df.shape,
        "columns": list(df.columns),
        "dtypes": df.dtypes,
        "describe": df.describe(include="all"),
        "info_text": "".join(buf_info),
    }


# --------------------------------------------------------------------------------------
# 2 & 3. MISSING VALUES + DUPLICATES
# --------------------------------------------------------------------------------------
def handle_missing_values(df: pd.DataFrame, report: PipelineReport) -> pd.DataFrame:
    """
    Detect and handle missing values.

    Strategy (justified per column type):
      - Numeric financial fields (income, loan_amount): impute with the MEDIAN.
        Rationale: loan/income data is right-skewed (a few very high earners), so the
        median is more robust to outliers than the mean and avoids distorting the
        distribution the way mean-imputation would.
      - Categorical fields (employment_status, property_area): impute with the MODE
        (most frequent category). Rationale: preserves the natural category balance
        instead of introducing an artificial "Unknown" class that would need special
        handling downstream.
      - credit_history (binary flag): impute with the MODE, since it is not a
        continuous variable and mean/median are not meaningful for a 0/1 flag.
      - Rows missing the target variable 'approved' are DROPPED, since a missing
        label cannot be reasonably imputed without introducing bias into any
        downstream approval-prediction model.
    """
    report.missing_before = df.isnull().sum().to_dict()

    # Flag - never silently blend in - values the pipeline has to invent for the credit-behaviour
    # fields. "No credit score on file" is not the same as "an average credit score", so these
    # rows stay in the book for reporting but are excluded when the model is trained.
    df = df.copy()
    for col in ("credit_score", "late_payments_12m", "credit_history"):
        df[f"{col}_imputed"] = df[col].isnull() if col in df.columns else False
    n_flagged = int(df[[f"{c}_imputed" for c in ("credit_score", "late_payments_12m", "credit_history")]].any(axis=1).sum())
    if n_flagged:
        report.log(f"{n_flagged} row(s) had a missing credit score, late-payment count or credit-history "
                   "flag: filled for reporting, marked *_imputed, and EXCLUDED from model training.")

    if "approved" in df.columns:
        before = len(df)
        df = df.dropna(subset=["approved"])
        dropped = before - len(df)
        if dropped:
            report.log(f"Dropped {dropped} row(s) missing the target label 'approved' (cannot impute a label).")

    numeric_median_cols = [c for c in ["applicant_income", "coapplicant_income", "loan_amount"] if c in df.columns]
    for col in numeric_median_cols:
        n_missing = df[col].isnull().sum()
        if n_missing:
            median_val = df[col].median()
            df[col] = df[col].fillna(median_val)
            report.log(f"Imputed {n_missing} missing value(s) in '{col}' with median ({median_val:,.2f}).")

    categorical_mode_cols = [c for c in ["employment_status", "property_area"] if c in df.columns]
    for col in categorical_mode_cols:
        n_missing = df[col].isnull().sum()
        if n_missing:
            mode_val = df[col].mode(dropna=True).iloc[0]
            df[col] = df[col].fillna(mode_val)
            report.log(f"Imputed {n_missing} missing value(s) in '{col}' with mode ('{mode_val}').")

    for col in [c for c in ["credit_history", "dependents", "loan_term_months", "credit_score", "late_payments_12m"] if c in df.columns]:
        n_missing = df[col].isnull().sum()
        if n_missing:
            mode_val = df[col].mode(dropna=True).iloc[0]
            df[col] = df[col].fillna(mode_val)
            report.log(f"Imputed {n_missing} missing value(s) in '{col}' with mode ({mode_val}).")

    report.missing_after = df.isnull().sum().to_dict()
    return df


def handle_duplicates(df: pd.DataFrame, report: PipelineReport) -> pd.DataFrame:
    """Detect and remove fully duplicated records, keeping the first occurrence."""
    dup_count = int(df.duplicated().sum())
    report.duplicates_found = dup_count
    if dup_count:
        df = df.drop_duplicates(keep="first").reset_index(drop=True)
        report.log(f"Removed {dup_count} exact duplicate record(s); kept first occurrence.")
    else:
        report.log("No exact duplicate records detected.")
    report.duplicates_dropped = dup_count
    return df


# --------------------------------------------------------------------------------------
# 4. VALIDATION
# --------------------------------------------------------------------------------------
def validate_data(df: pd.DataFrame, report: PipelineReport, drop_invalid: bool = True) -> pd.DataFrame:
    """
    Validate value ranges, categories and business-rule constraints.
    Invalid rows are flagged and (optionally) dropped, with counts logged for transparency.
    """
    invalid_mask = pd.Series(False, index=df.index)
    flags = {}

    def flag(name: str, mask: pd.Series):
        n = int(mask.sum())
        flags[name] = n
        nonlocal invalid_mask
        invalid_mask = invalid_mask | mask
        if n:
            report.log(f"Validation: {n} row(s) failed rule '{name}'.")

    if "applicant_income" in df.columns:
        flag("applicant_income_out_of_range",
             ~df["applicant_income"].between(MIN_INCOME, MAX_INCOME) | (df["applicant_income"] < 0))
    if "coapplicant_income" in df.columns:
        flag("coapplicant_income_negative", df["coapplicant_income"] < 0)
    if "loan_amount" in df.columns:
        flag("loan_amount_out_of_range", ~df["loan_amount"].between(MIN_LOAN, MAX_LOAN))
    if "loan_term_months" in df.columns:
        flag("loan_term_out_of_range", ~df["loan_term_months"].between(MIN_TERM, MAX_TERM))
    if "dependents" in df.columns:
        flag("dependents_out_of_range", ~df["dependents"].between(0, MAX_DEPENDENTS))
    if "credit_history" in df.columns:
        flag("credit_history_invalid", ~df["credit_history"].isin([0, 1]))
    if "employment_status" in df.columns:
        flag("employment_status_invalid", ~df["employment_status"].isin(VALID_EMPLOYMENT_STATUSES))
    if "property_area" in df.columns:
        flag("property_area_invalid", ~df["property_area"].isin(VALID_PROPERTY_AREAS))
    if "credit_score" in df.columns:
        flag("credit_score_out_of_range", ~df["credit_score"].between(MIN_CREDIT_SCORE, MAX_CREDIT_SCORE))
    if "late_payments_12m" in df.columns:
        flag("late_payments_12m_out_of_range", ~df["late_payments_12m"].between(0, MAX_LATE_PAYMENTS_12M))
    if "approved" in df.columns:
        flag("approved_invalid", ~df["approved"].isin([0, 1]))
    if DATE_COL in df.columns:
        parsed = parse_dates(df[DATE_COL])
        flag("application_date_invalid", parsed.isna())
        flag("application_date_in_future", parsed > today_local())
        flag("application_date_too_old", parsed < MIN_APPLICATION_DATE)
        df[DATE_COL] = parsed

    report.invalid_rows_flagged = flags
    n_invalid_total = int(invalid_mask.sum())

    if n_invalid_total == 0:
        report.log("Data validation passed: no rule violations detected across all fields.")
        return df

    if drop_invalid:
        df = df.loc[~invalid_mask].reset_index(drop=True)
        report.invalid_rows_dropped = n_invalid_total
        report.log(f"Dropped {n_invalid_total} row(s) that violated one or more validation rules.")
    else:
        df["is_valid_record"] = ~invalid_mask
        report.log(f"Flagged {n_invalid_total} row(s) as invalid via 'is_valid_record' column (not dropped).")

    return df


# --------------------------------------------------------------------------------------
# 4b. VALIDATE NEW APPLICATIONS (batch scoring) - row by row, with reasons
# --------------------------------------------------------------------------------------
APPLICATION_NUMERIC = ["applicant_income", "coapplicant_income", "loan_amount", "loan_term_months",
                       "credit_history", "dependents", "credit_score", "late_payments_12m"]
APPLICATION_CATEGORICAL = ["employment_status", "property_area"]
_RANGES = {
    "applicant_income": (MIN_INCOME, MAX_INCOME), "coapplicant_income": (MIN_INCOME, MAX_INCOME),
    "loan_amount": (1, MAX_LOAN), "loan_term_months": (MIN_TERM, MAX_TERM),
    "credit_history": (0, 1), "dependents": (0, MAX_DEPENDENTS),
    "credit_score": (MIN_CREDIT_SCORE, MAX_CREDIT_SCORE), "late_payments_12m": (0, MAX_LATE_PAYMENTS_12M),
}
OPTIONAL_NUMERIC = ["existing_monthly_debt", "collateral_value"]
_WHOLE = {"credit_history", "dependents", "late_payments_12m", "loan_term_months", "credit_score"}


def validate_applications(raw: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Check an uploaded file of NEW applications. Nothing is guessed or filled in.

    Returns ``(valid, issues)``: ``valid`` holds the rows that passed every check (numeric
    columns cast, categories normalised); ``issues`` lists every problem found, one line each,
    with the spreadsheet row number (header = row 1) so it can be fixed at source."""
    df = raw.copy()
    problems: list[dict] = []
    bad_rows: set = set()

    def add(idx, field, problem, value):
        bad_rows.add(idx)
        problems.append({"file_row": int(idx) + 2, "field": field, "problem": problem,
                         "value": "" if pd.isna(value) else str(value)[:40]})

    for col in APPLICATION_NUMERIC:
        original = df[col]
        num = pd.to_numeric(original, errors="coerce")
        lo, hi = _RANGES[col]
        for idx in df.index:
            v, o = num.at[idx], original.at[idx]
            if pd.isna(o) or str(o).strip() == "":
                add(idx, col, "missing", o)
            elif pd.isna(v) or not np.isfinite(v):
                add(idx, col, "not a number", o)
            elif v < lo or v > hi:
                add(idx, col, f"outside {lo:,} to {hi:,}", o)
            elif col in _WHOLE and float(v) != int(v):
                add(idx, col, "must be a whole number", o)
        df[col] = num

    for col in APPLICATION_CATEGORICAL:
        df[col] = (df[col].astype("string").str.strip().str.lower().str.replace(r"[\s\-]+", "_", regex=True))
        allowed = VALID_EMPLOYMENT_STATUSES if col == "employment_status" else VALID_PROPERTY_AREAS
        for idx in df.index[~df[col].isin(allowed)]:
            add(idx, col, "missing" if pd.isna(df.at[idx, col]) else f"not one of {', '.join(sorted(allowed))}",
                df.at[idx, col])

    # Optional columns (not model inputs - they feed policy, pricing and expected loss). Absent = 0.
    for col in OPTIONAL_NUMERIC:
        if col not in df.columns:
            df[col] = 0.0
            continue
        original = df[col]
        num = pd.to_numeric(original, errors="coerce")
        for idx in df.index:
            o, v = original.at[idx], num.at[idx]
            if pd.isna(o) or str(o).strip() == "":
                num.at[idx] = 0.0                       # blank optional value = none
            elif pd.isna(v) or not np.isfinite(v):
                add(idx, col, "not a number", o)
            elif v < 0 or v > MAX_LOAN * 10:
                add(idx, col, f"outside 0 to {MAX_LOAN * 10:,}", o)
        df[col] = num

    # Optional application date. Absent column = received today; a value that is present must be a
    # real date, not in the future and not before 2000.
    if DATE_COL in df.columns:
        original = df[DATE_COL]
        parsed = parse_dates(original)
        today = today_local()
        for idx in df.index:
            o, v = original.at[idx], parsed.at[idx]
            if pd.isna(o) or str(o).strip() == "":
                add(idx, DATE_COL, "missing (leave the whole column out to use today)", o)
            elif pd.isna(v):
                add(idx, DATE_COL, "not a date (use YYYY-MM-DD or DD/MM/YYYY)", o)
            elif v > today:
                add(idx, DATE_COL, "in the future", o)
            elif v < MIN_APPLICATION_DATE:
                add(idx, DATE_COL, "before 2000", o)
        df[DATE_COL] = parsed
    else:
        df[DATE_COL] = today_local()

    issues = pd.DataFrame(problems, columns=["file_row", "field", "problem", "value"])
    valid = df.loc[~df.index.isin(bad_rows)].copy()
    for col in _WHOLE:
        valid[col] = valid[col].astype(int)
    for col in APPLICATION_CATEGORICAL:
        valid[col] = valid[col].astype(str)
    return valid, issues


# --------------------------------------------------------------------------------------
# 5. FEATURE ENGINEERING (derived columns)
# --------------------------------------------------------------------------------------
def _emi(principal: float, annual_rate: float, term_months: float) -> float:
    """Standard amortizing-loan EMI (Equal Monthly Installment) formula."""
    if term_months <= 0 or principal <= 0:
        return 0.0
    r = annual_rate / 12
    if r == 0:
        return principal / term_months
    factor = (1 + r) ** term_months
    return principal * r * factor / (factor - 1)


def engineer_features(df: pd.DataFrame, report: PipelineReport) -> pd.DataFrame:
    """Build all predictors from the new 11-column dataset.

    The important change is that credit_score and late_payments_12m are retained and
    expanded into several history-aware indicators. No target/approved value is used as a
    feature, so there is no direct target leakage.
    """
    added = []
    df = df.copy()

    df["total_income"] = df["applicant_income"] + df["coapplicant_income"]
    added.append("total_income")
    df["loan_to_income_ratio"] = safe_ratio(df["loan_amount"], df["total_income"]).round(4)
    added.append("loan_to_income_ratio")
    df["loan_to_annual_income"] = safe_ratio(df["loan_amount"] / 12, df["total_income"]).round(4)
    added.append("loan_to_annual_income")
    df["estimated_emi"] = df.apply(lambda r: _emi(r["loan_amount"], ASSUMED_ANNUAL_INTEREST_RATE, r["loan_term_months"]), axis=1).round(2)
    added.append("estimated_emi")
    df["debt_to_income_ratio"] = safe_ratio(df["estimated_emi"], df["total_income"]).round(4)
    added.append("debt_to_income_ratio")
    df["household_size"] = df["dependents"] + 1 + (df["coapplicant_income"] > 0).astype(int)
    added.append("household_size")

    # History-derived features.
    df["credit_score_band"] = pd.cut(
        df["credit_score"], bins=[-np.inf, 579, 669, 739, 799, np.inf],
        labels=[0, 1, 2, 3, 4]
    ).astype(float)
    added.append("credit_score_band")
    df["late_payment_rate"] = (df["late_payments_12m"] / 12.0).clip(0, 1)
    added.append("late_payment_rate")
    df["credit_payment_stress"] = (
        (850 - df["credit_score"]) / 550.0 + df["late_payment_rate"]
    ).clip(lower=0)
    added.append("credit_payment_stress")
    df["income_per_dependent"] = df["total_income"] / (df["dependents"] + 1)
    added.append("income_per_dependent")
    df["loan_burden_x_credit"] = df["loan_to_annual_income"] * (850 - df["credit_score"]).clip(lower=0) / 550.0
    added.append("loan_burden_x_credit")

    # Descriptive portfolio bands.
    try:
        df["income_bracket"] = pd.qcut(df["total_income"], q=3, labels=["Low", "Medium", "High"], duplicates="drop")
    except ValueError:
        df["income_bracket"] = "Medium"
    added.append("income_bracket")
    df["loan_size_category"] = pd.cut(df["loan_amount"], bins=[-np.inf, 100_000, 200_000, 350_000, np.inf], labels=["Small", "Medium", "Large", "Jumbo"])
    added.append("loan_size_category")

    def _risk(row) -> str:
        score = 0
        if row["credit_history"] == 0: score += 2
        if row["credit_score"] < RISK_SCORE_BAD_BELOW: score += 2
        elif row["credit_score"] < RISK_SCORE_WEAK_BELOW: score += 1
        if row["late_payments_12m"] >= RISK_LATE_SEVERE_AT: score += 2
        elif row["late_payments_12m"] >= RISK_LATE_ANY_AT: score += 1
        if row["debt_to_income_ratio"] > RISK_DTI_HIGH: score += 2
        elif row["debt_to_income_ratio"] > RISK_DTI_MID: score += 1
        if row["loan_to_annual_income"] > LTI_HIGH_THRESHOLD: score += 1
        if row["employment_status"] == "unemployed": score += 1
        if score >= RISK_HIGH_MIN: return "High"
        if score >= RISK_MEDIUM_MIN: return "Medium"
        return "Low"

    df["risk_level"] = df.apply(_risk, axis=1)
    added.append("risk_level")

    if DATE_COL in df.columns:
        df[DATE_COL] = parse_dates(df[DATE_COL])
        add_date_parts(df)
        added += ["application_month", "application_quarter", "application_year", "application_weekday"]
        report.log(f"Application dates run from {df[DATE_COL].min():%d %b %Y} to {df[DATE_COL].max():%d %b %Y} "
                   f"({df['application_month'].nunique()} months). Dates are used for filtering and "
                   "time-based validation only, never as a model input.")
    report.columns_added = added
    report.log(f"Engineered {len(added)} derived columns, including credit-score and 12-month late-payment history features.")
    return df


# --------------------------------------------------------------------------------------
# ORCHESTRATOR
# --------------------------------------------------------------------------------------
def run_pipeline(path: str | Path, drop_invalid: bool = True) -> tuple[pd.DataFrame, PipelineReport]:
    """Run the full load -> clean -> validate -> engineer pipeline end-to-end."""
    report = PipelineReport()
    df = load_data(path)
    report.rows_in = len(df)

    df = handle_missing_values(df, report)
    df = handle_duplicates(df, report)
    df = validate_data(df, report, drop_invalid=drop_invalid)
    df = engineer_features(df, report)

    report.rows_out = len(df)
    return df, report


if __name__ == "__main__":
    clean_df, rpt = run_pipeline(Path(__file__).resolve().parent.parent / "data" / "loan_data.csv")
    print(rpt.summary())
    out_path = Path(__file__).resolve().parent.parent / "data" / "loan_data_clean.csv"
    clean_df.to_csv(out_path, index=False)
    print(f"\nClean dataset written to: {out_path}")
