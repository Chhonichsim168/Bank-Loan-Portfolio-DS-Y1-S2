# 🏦 Bank Loan Portfolio Analytics

**An end-to-end, professional analytics system for retail loan portfolio monitoring, risk
segmentation, and approval-decision support** — built with Python, Pandas, scikit-learn, and
an interactive Streamlit dashboard.

![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white)
![Streamlit](https://img.shields.io/badge/Streamlit-App-FF4B4B?logo=streamlit&logoColor=white)
![Pandas](https://img.shields.io/badge/Pandas-Data%20Analysis-150458?logo=pandas&logoColor=white)
![scikit-learn](https://img.shields.io/badge/scikit--learn-Model-F7931E?logo=scikit-learn&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green)
![Tests](https://img.shields.io/badge/tests-14%20passing-brightgreen)

---

## 📌 Table of Contents

- [Overview](#-overview)
- [Screenshots](#-screenshots)
- [Business Problem & Project Scope](#-business-problem--project-scope)
- [Objectives](#-objectives)
- [Analytical Questions](#-analytical-questions)
- [Dataset](#-dataset)
- [Data Dictionary](#-data-dictionary)
- [Project Structure](#-project-structure)
- [Features](#-features)
- [Installation & Quick Start](#-installation--quick-start)
- [Methodology / Workflow](#-methodology--workflow)
- [Key Findings](#-key-findings)
- [Recommendations](#-recommendations)
- [Predictive Model](#-predictive-model)
- [Testing](#-testing)
- [Limitations & Disclaimer](#-limitations--disclaimer)
- [Tech Stack](#-tech-stack)
- [License](#-license)

---

## 🔎 Overview

Bank Loan Portfolio Analytics is a complete data analytics system, not just a notebook: a
reusable data pipeline, a statistics & visualization layer, a predictive approval model, an
interactive multi-page dashboard, and an auto-generated stakeholder report — all built on a
2,000-row historical loan application dataset and organized as a clean, professional,
GitHub-ready Python project.

It is designed to answer the question every retail lending team eventually asks:
**"What actually drives our approval decisions, and where is our risk concentrated?"**

---

## 🖼️ Screenshots

| Executive Overview | Predictive Model |
|---|---|
| ![Overview](docs/screenshots/01_executive_overview.png) | ![Model](docs/screenshots/02_predictive_model.png) |

| Risk Segmentation | Applicant What-If Simulator |
|---|---|
| ![Risk](docs/screenshots/03_risk_segmentation.png) | ![Simulator](docs/screenshots/04_applicant_simulator.png) |

| Analytical Questions |
|---|
| ![Questions](docs/screenshots/05_analytical_questions.png) |

---

## 🧩 Business Problem & Project Scope

Retail lending teams process thousands of loan applications, but approval decisions are often
made without a systematic, data-driven view of what actually predicts approval, how risk is
distributed across the portfolio, or where underwriting policy could be sharpened. This leads to
**inconsistent underwriting, unmonitored concentration risk, and missed opportunities** to flag
high-risk segments early or retain bankable customers who are being rejected for the wrong reasons.

**This project analyzes a portfolio of 2,000 historical loan applications** — covering applicant
and co-applicant income, loan amount and term, credit history, employment status, property area,
and dependents — to surface the true drivers of approval, quantify risk concentration, and provide
a transparent, data-driven decision-support tool for loan officers and risk management teams.

**In scope:**
- Applicant/co-applicant income, loan amount & term, credit history, employment status, property
  area, dependents, and the resulting approval outcome.
- Data cleaning, validation, feature engineering, descriptive & inferential statistics, visual
  analytics, rule-based risk segmentation, and a predictive approval model.

**Out of scope / limitations:**
- This dataset does not include external bureau credit scores, collateral valuation, existing
  liabilities beyond the stated loan, macroeconomic conditions, or fraud signals.
- The predictive model is an **illustrative decision-support tool**, not a production underwriting
  system (see [Limitations & Disclaimer](#-limitations--disclaimer)).

---

## 🎯 Objectives

1. **Quantify** the key drivers of loan approval (credit history, income, debt ratios, employment,
   property area) with statistical evidence — target: identify at least 3 statistically meaningful drivers.
2. **Segment** the loan portfolio into actionable, explainable risk tiers and measure each tier's
   size and approval performance.
3. **Build and evaluate** a transparent predictive model that estimates approval probability from
   application-form data, achieving **ROC AUC ≥ 0.80**.

## ❓ Analytical Questions

1. How strongly does credit history influence loan approval?
2. Does higher applicant income correlate with higher approval likelihood?
3. Do approval patterns differ across property area and employment type?
4. What share of the portfolio falls into each risk segment, and how do they perform?
5. At what debt-to-income ratio does approval likelihood drop off sharply?

*(All 5 questions are answered with tables, charts, and written interpretation on the "🧭
Analytical Questions" page of the dashboard, and in Section 8 of the generated HTML report.)*

---

## 📂 Dataset

- **File:** `data/loan_data.csv`
- **Size:** 2,000 rows × 9 raw columns (well above the 500-row minimum requirement)
- **Grain:** one row per loan application
- **Target:** `approved` (binary: 1 = approved, 0 = rejected), roughly balanced at ~53% / 47%

## 📖 Data Dictionary

See the full table in [`docs/data_dictionary.md`](docs/data_dictionary.md), also embedded in the
dashboard's "Data Dictionary & About" page and the generated report. Summary:

| Field | Type | Description |
|---|---|---|
| `applicant_income` | float | Primary applicant's monthly income (USD) |
| `coapplicant_income` | float | Co-applicant's monthly income (USD) |
| `loan_amount` | float | Requested loan principal (USD) |
| `loan_term_months` | int | Requested repayment term (months) |
| `credit_history` | int (0/1) | 1 = good credit history, 0 = poor/none |
| `dependents` | int | Number of financial dependents |
| `employment_status` | categorical | salaried / self_employed / unemployed |
| `property_area` | categorical | urban / semiurban / rural |
| `approved` | int (0/1) | **Target** — 1 = approved, 0 = rejected |
| `total_income` *(derived)* | float | `applicant_income + coapplicant_income` |
| `loan_to_income_ratio` *(derived)* | float | `loan_amount / total_income` |
| `estimated_emi` *(derived)* | float | Amortized monthly installment @ assumed 8.5% p.a. |
| `debt_to_income_ratio` *(derived)* | float | `estimated_emi / total_income` |
| `income_bracket` *(derived)* | categorical | Low / Medium / High tertile of income |
| `loan_size_category` *(derived)* | categorical | Small / Medium / Large / Jumbo |
| `household_size` *(derived)* | int | Estimated household size |
| `risk_level` *(derived)* | categorical | Low / Medium / High composite risk score |

---

## 🗂️ Project Structure

```
bank_loan_analytics/
├── app.py                          # Main Streamlit dashboard (10 pages)
├── generate_report.py              # Builds a standalone HTML analytics report
├── requirements.txt
├── LICENSE
├── .gitignore
├── README.md
├── data/
│   └── loan_data.csv               # Raw dataset (2,000 rows)
├── docs/
│   ├── data_dictionary.md          # Full field-by-field data dictionary
│   └── screenshots/                # Dashboard screenshots used in this README
├── src/
│   ├── data_pipeline.py            # Load, clean, validate, engineer features
│   ├── analytics.py                # Filtering, grouping, pivots, statistics, Q&A functions
│   ├── visualizations.py           # 8 matplotlib/seaborn chart functions
│   └── risk_model.py               # Logistic regression approval-prediction model
├── reports/
│   ├── figures/                    # PNG chart exports (generated)
│   └── Bank_Loan_Portfolio_Analytics_Report.html   # Standalone report (generated)
└── tests/
    └── test_pipeline.py            # 14 unit tests covering pipeline, analytics, model
```

---

## ✨ Features

- **Robust data pipeline** — structural inspection, missing-value imputation (median/mode with
  documented justification), duplicate removal, and 9 explicit validation rules, all captured in
  an auditable `PipelineReport`.
- **8 engineered features** — total income, loan-to-income ratio, estimated EMI, debt-to-income
  ratio, income bracket, loan size category, household size, and a transparent rule-based risk
  score.
- **Full exploratory & statistical toolkit** — filtering, sorting, grouping, pivot tables /
  crosstabs, correlation analysis, and mean/median/mode/std/variance summaries.
- **8 professional visualizations** — bar, line, histogram, pie, scatter, box plot, correlation
  heatmap, and stacked bar, every one with a title, axis labels, and a written interpretation.
- **10-page interactive Streamlit dashboard** with a custom banking-grade visual theme:
  Executive Overview, Data Quality & Pipeline, Exploratory Analysis, Statistical Analysis,
  Analytical Questions, Risk Segmentation, Predictive Model, an **Applicant What-If Simulator**,
  Findings & Recommendations, and a Data Dictionary page — with live sidebar filters that update
  every page instantly.
- **Predictive approval model** (logistic regression, ROC AUC ≈ 0.86) with confusion matrix, ROC
  curve, and feature-importance visualization, plus a single-applicant scoring function used by
  the What-If Simulator.
- **Standalone HTML report generator** — produces a self-contained, presentation-ready report
  with every chart embedded, for offline sharing or archiving a specific data snapshot.
- **14 automated unit tests** covering data cleaning, validation, feature engineering, analytics,
  and the model — all passing.

---

## 🚀 Installation & Quick Start

### 1. Clone the repository
```bash
git clone https://github.com/<your-username>/bank-loan-portfolio-analytics.git
cd bank-loan-portfolio-analytics
```

### 2. Create a virtual environment (recommended)
```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

### 4. Run the interactive dashboard
```bash
streamlit run app.py
```
Then open the URL Streamlit prints (typically `http://localhost:8501`) in your browser.

### 5. (Optional) Run the standalone data pipeline
```bash
python src/data_pipeline.py
```
Prints a full data-quality audit report and writes `data/loan_data_clean.csv`.

### 6. (Optional) Generate the static HTML report
```bash
python generate_report.py
```
Writes `reports/Bank_Loan_Portfolio_Analytics_Report.html` — open it directly in any browser.

### 7. (Optional) Run the test suite
```bash
pytest -v
```

---

## 🔁 Methodology / Workflow

```
Problem Definition → Objectives & Questions → Dataset Collection → Data Dictionary
   → Data Understanding (df.head/shape/columns/info/describe)
   → Data Cleaning (missing values, duplicates)
   → Data Validation (ranges, categories, invalid entries)
   → Data Transformation (8 derived columns)
   → Exploratory Data Analysis (filter, sort, group, pivot)
   → Statistical Analysis (mean/median/mode/std/variance, correlation)
   → Data Visualization (8 chart types)
   → Interpretation (written commentary under every chart/table)
   → Findings (5 key findings)
   → Recommendations (6 actionable recommendations)
   → GitHub packaging + Streamlit live demo
```

Every stage above maps 1:1 to a function in `src/` and a page in `app.py`, so the dashboard *is*
the live demonstration of the full workflow.

---

## 💡 Key Findings

1. **Credit history is the single strongest driver of approval** — good-history applicants are
   approved ~63% of the time vs. only ~20% for those without one, a >40 percentage-point gap.
2. **Debt-to-income ratio, not raw income, is the key affordability signal** — it correlates more
   strongly with approval than income alone, and approval collapses once DTI passes roughly 30–40%.
3. **The portfolio is concentrated in low-to-medium risk** — about 59% of applications are
   Low-risk and only ~6% High-risk, indicating a generally healthy book with a small segment
   needing closer underwriting attention.
4. **Employment type and property area create measurable approval gaps** — self-employed
   applicants and rural properties consistently show lower approval rates than salaried
   applicants and urban/semiurban properties, even after accounting for income.
5. **A simple, explainable model achieves strong predictive performance** — an 8-feature logistic
   regression reaches ROC AUC ≈ 0.86 using only application-form data, showing a lightweight model
   can meaningfully support (not replace) underwriting triage.

## ✅ Recommendations

1. Weight credit history heavily in automated pre-screening, but pair it with a manual review path
   for applicants with poor history but strong income and low debt-to-income ratio.
2. Adopt an explicit debt-to-income cap (e.g., 40–45%) as underwriting policy, since approval
   likelihood collapses sharply beyond that threshold.
3. Investigate the self-employed / rural approval gap for process friction (e.g., harder-to-verify
   income) versus genuine risk difference, to keep underwriting fair and consistent.
4. Introduce risk-based pricing or a collateral tier for the High-risk segment rather than blanket
   rejection, to retain serviceable customers while pricing for risk.
5. Deploy the predictive model only as a **triage aid** flagging applications for priority manual
   review — never as an autonomous approver — and monitor it quarterly for drift and fair-lending
   compliance.
6. Expand the dataset with bureau credit scores, existing liabilities, and collateral value to
   improve model accuracy and reduce reliance on proxy variables like employment status.

---

## 🤖 Predictive Model

A **Logistic Regression** classifier (scikit-learn, with standardized numeric features and
one-hot encoded categoricals) trained on an 8-feature subset of the engineered dataset:

| Metric | Score |
|---|---|
| Accuracy | ~79% |
| Precision | ~79% |
| Recall | ~83% |
| F1 Score | ~81% |
| **ROC AUC** | **~0.86** |

The model is intentionally simple and explainable (linear coefficients, no black-box ensemble) so
every prediction can be justified in plain business terms — see the "Predictive Model" and
"Applicant Simulator" pages in the dashboard.

---

## 🧪 Testing

```bash
pytest -v
```
14 tests cover: dataset size, pipeline correctness, missing-value imputation, duplicate removal,
validation-rule enforcement, derived-column correctness, analytics functions, and model training —
all passing.

---

## ⚠️ Limitations & Disclaimer

This system is an **educational / decision-support analytics project**, not a certified credit
underwriting product. Specifically:

- The dataset excludes bureau credit scores, collateral, other liabilities, macroeconomic factors,
  and fraud signals — real underwriting requires much more than what is modeled here.
- The `estimated_emi` field uses a single **assumed** 8.5% annual interest rate for illustration,
  not an actual contracted rate.
- The predictive model is trained on historical approval labels, which may reflect **past biases**;
  it must not be used as the sole basis for real credit decisions and should always be paired with
  bureau data, human underwriting judgment, and fair-lending compliance review before any
  operational use.

---

## 🛠️ Tech Stack

- **Language:** Python 3.10+
- **Data processing:** Pandas, NumPy
- **Machine learning:** scikit-learn (Logistic Regression, pipeline, metrics)
- **Visualization:** Matplotlib, Seaborn, Plotly
- **Dashboard:** Streamlit
- **Testing:** pytest

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).

---

*Built as a professional, portfolio-ready demonstration of an end-to-end bank loan analytics
system — from raw CSV to interactive, decision-support dashboard.*
