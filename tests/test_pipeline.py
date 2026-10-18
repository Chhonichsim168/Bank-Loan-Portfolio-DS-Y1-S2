"""
Unit tests for the Bank Loan Portfolio Analytics data pipeline, analytics,
and risk model modules. Run with:  pytest -v
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.data_pipeline import (
    run_pipeline, handle_missing_values, handle_duplicates, validate_data,
    engineer_features, PipelineReport,
)
from src import analytics as an
from src.risk_model import train_model, predict_single_applicant

DATA_PATH = ROOT / "data" / "loan_data.csv"


@pytest.fixture(scope="module")
def clean_df():
    df, _ = run_pipeline(str(DATA_PATH))
    return df


def test_dataset_has_minimum_rows():
    raw = pd.read_csv(DATA_PATH)
    assert len(raw) >= 500, "Dataset must contain at least 500 rows"


def test_pipeline_runs_end_to_end(clean_df):
    assert len(clean_df) > 0
    assert clean_df.isnull().sum().sum() == 0, "Clean dataset should have no missing values"


def test_no_duplicate_rows_after_cleaning(clean_df):
    assert clean_df.duplicated().sum() == 0


def test_derived_columns_present(clean_df):
    expected = {
        "total_income", "loan_to_income_ratio", "estimated_emi",
        "debt_to_income_ratio", "income_bracket", "loan_size_category",
        "household_size", "risk_level", "loan_to_annual_income",
    }
    assert expected.issubset(set(clean_df.columns))


def test_total_income_calculation(clean_df):
    recomputed = clean_df["applicant_income"] + clean_df["coapplicant_income"]
    assert np.allclose(clean_df["total_income"], recomputed)


def test_risk_level_values_valid(clean_df):
    assert set(clean_df["risk_level"].unique()).issubset({"Low", "Medium", "High"})


def test_validation_rejects_bad_income():
    bad_df = pd.DataFrame({
        "applicant_income": [-500, 5000], "coapplicant_income": [0, 0],
        "loan_amount": [10000, 10000], "loan_term_months": [360, 360],
        "credit_history": [1, 1], "dependents": [0, 0],
        "employment_status": ["salaried", "salaried"], "property_area": ["urban", "urban"],
        "approved": [1, 1],
    })
    report = PipelineReport()
    cleaned = validate_data(bad_df, report, drop_invalid=True)
    assert len(cleaned) == 1  # the negative-income row should be dropped


def test_missing_value_imputation():
    df = pd.DataFrame({
        "applicant_income": [1000, np.nan, 3000],
        "coapplicant_income": [0, 0, 0],
        "loan_amount": [50000, 60000, np.nan],
        "loan_term_months": [360, 360, 360],
        "credit_history": [1, 1, 1],
        "dependents": [0, 0, 0],
        "employment_status": ["salaried", None, "salaried"],
        "property_area": ["urban", "urban", "urban"],
        "approved": [1, 0, 1],
    })
    report = PipelineReport()
    cleaned = handle_missing_values(df, report)
    assert cleaned.isnull().sum().sum() == 0


def test_duplicate_removal():
    df = pd.DataFrame({"a": [1, 1, 2], "b": [2, 2, 3]})
    report = PipelineReport()
    cleaned = handle_duplicates(df, report)
    assert len(cleaned) == 2
    assert report.duplicates_found == 1


def test_approval_rate_by_returns_expected_columns(clean_df):
    g = an.approval_rate_by(clean_df, "employment_status")
    assert "approval_rate_pct" in g.columns
    assert (g["approval_rate_pct"] >= 0).all() and (g["approval_rate_pct"] <= 100).all()


def test_correlation_matrix_symmetric(clean_df):
    corr = an.correlation_matrix(clean_df, ["applicant_income", "loan_amount", "approved"])
    assert np.allclose(corr.values, corr.values.T)


def test_filter_portfolio_narrows_results(clean_df):
    filtered = an.filter_portfolio(clean_df, employment_status=["salaried"])
    assert (filtered["employment_status"] == "salaried").all()
    assert len(filtered) <= len(clean_df)


def test_model_trains_and_scores_reasonably(clean_df):
    result = train_model(clean_df)
    assert 0.5 < result.roc_auc <= 1.0, "Model should beat random guessing"
    assert result.accuracy > 0.5


def test_predict_single_applicant(clean_df):
    result = train_model(clean_df)
    applicant = dict(
        applicant_income=6000, coapplicant_income=2000, loan_amount=120000,
        loan_term_months=360, credit_history=1, dependents=1,
        employment_status="salaried", property_area="urban",
        credit_score=700, late_payments_12m=0,
    )
    pred, proba = predict_single_applicant(result.pipeline, applicant)
    assert pred in (0, 1)
    assert 0.0 <= proba <= 1.0
