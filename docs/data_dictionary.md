# Data Dictionary — Bank Loan Portfolio Analytics

Source file: `data/loan_data.csv` (2,000 rows × 11 raw columns; 14 derived columns
are added by `src/data_pipeline.py` during processing).

## Raw Fields

| Field Name | Data Type | Description | Example Value |
|---|---|---|---|
| `application_date` | date (optional) | Day the application was received, `YYYY-MM-DD` or `DD/MM/YYYY`. Not in the future, not before 2000. Used for filters, trends and out-of-time validation, never as a model input | `2026-03-12` |
| `applicant_income` | float | Primary applicant's gross monthly income (USD) | `5324.99` |
| `coapplicant_income` | float | Co-applicant's gross monthly income (USD); `0` if none | `1429.28` |
| `loan_amount` | float | Requested loan principal (USD) | `134000.00` |
| `loan_term_months` | int | Requested repayment term, in months | `360` |
| `credit_history` | int (0/1) | `1` = good credit history on file, `0` = poor/no history | `1` |
| `dependents` | int | Number of financial dependents of the applicant | `2` |
| `employment_status` | categorical (str) | One of: `salaried`, `self_employed`, `unemployed` | `salaried` |
| `property_area` | categorical (str) | One of: `urban`, `semiurban`, `rural` | `urban` |
| `credit_score` | int | Numeric credit score, 300 to 850. Higher is better | `712` |
| `late_payments_12m` | int | Count of late payments in the last 12 months, 0 to 24. A bare count: no severity, amount or recency | `0` |
| `approved` | int (0/1) | **Target variable**: `1` = loan approved, `0` = rejected | `1` |

## Derived / Calculated Fields (added by the pipeline)

| Field Name | Data Type | Formula | Description | Example Value |
|---|---|---|---|---|
| `application_month` | string | `application_date` as `YYYY-MM` | Month bucket for trends | `2026-03` |
| `application_quarter` | string | `YYYY-Qn` | Quarter bucket for stability checks | `2026-Q1` |
| `application_year` | int | calendar year | Year bucket for driver and fairness comparisons | `2026` |
| `application_weekday` | string | day name | Day the application arrived | `Thursday` |
| `total_income` | float | `applicant_income + coapplicant_income` | True household income used for affordability | `6754.27` |
| `loan_to_income_ratio` | float | `loan_amount / total_income` | Loan size as a multiple of **monthly** income. Kept for continuity; not used for policy | `19.85` |
| `loan_to_annual_income` | float | `loan_amount / (total_income × 12)` | Loan size as a multiple of **annual** income. This is the affordability measure every rule in the app is written against | `1.65` |
| `estimated_emi` | float | Standard amortization formula at an assumed 8.5% p.a. rate | Illustrative monthly installment | `1030.42` |
| `debt_to_income_ratio` | float | `estimated_emi / total_income` | Core affordability / credit-risk metric | `0.15` |
| `income_bracket` | categorical | Tertile split of `total_income` | `Low` / `Medium` / `High` income segment | `Medium` |
| `loan_size_category` | categorical | Binned `loan_amount` (≤100k / ≤200k / ≤350k / >350k) | `Small` / `Medium` / `Large` / `Jumbo` | `Medium` |
| `credit_score_band` | int (0–4) | Credit score banded: <580, 580–669, 670–739, 740–799, 800+ | Credit-quality band | `2` |
| `late_payment_rate` | float | `late_payments_12m / 12`, capped at 1 | Share of the last 12 months with a late payment, as a rate | `0.08` |
| `credit_payment_stress` | float | `(850 − credit_score) / 550 + late_payment_rate` | Score shortfall and late-payment frequency in one number | `0.33` |
| `loan_burden_x_credit` | float | `loan_to_annual_income × (850 − credit_score) / 550` | Large loan on a weak score counts for more than either alone | `0.25` |
| `income_per_dependent` | float | `total_income / (dependents + 1)` | Income available per household dependent | `2250.00` |
| `household_size` | int | `dependents + 1 (+1 if coapplicant_income > 0)` | Estimated household size | `3` |
| `risk_level` | categorical | Additive rule, max 10 points: no credit history `+2`; credit score <580 `+2` (580–669 `+1`); 3+ late payments in 12m `+2` (1–2 `+1`); DTI > 45% `+2` (30–45% `+1`); not employed `+1`; loan > 3.5× annual income `+1`. Score ≥6 = High, 3–5 = Medium, 0–2 = Low | `Low` / `Medium` / `High` risk tier | `Low` |

## Validation Rules Applied

| Field | Rule |
|---|---|
| `applicant_income` | Must be between 0 and 200,000 |
| `coapplicant_income` | Must be ≥ 0 |
| `loan_amount` | Must be between 0 and 5,000,000 |
| `loan_term_months` | Must be between 12 and 480 (1–40 years) |
| `dependents` | Must be between 0 and 10 |
| `credit_history` | Must be 0 or 1 |
| `credit_score` | Must be between 300 and 850 |
| `late_payments_12m` | Must be between 0 and 24 |
| `employment_status` | Must be one of the 3 defined categories |
| `property_area` | Must be one of the 3 defined categories |
| `approved` | Must be 0 or 1 |

## Assumptions

- `estimated_emi` uses a single, illustrative annual interest rate of **8.5%** applied
  uniformly across all loans, since the raw dataset does not include an interest rate
  field. This is clearly documented in the dashboard and report so it is never mistaken
  for an actual contracted rate.
- Income fields are treated as **monthly** figures (consistent with loan terms expressed
  in months and loan-to-income ratios in the observed data range).
- Because income is monthly, `loan_to_income_ratio` has a median of roughly **18x** and is
  not comparable to the single-digit "3.5x income" multiples lending policy is written in.
  Any affordability threshold must be applied to `loan_to_annual_income` instead. A
  threshold of `5` applied to the monthly column fires on 97.6% of the book — it looks like
  a rule but behaves like a constant. See `LTI_HIGH_THRESHOLD` in `src/data_pipeline.py`
  and the regression test in `tests/test_decisioning.py`.
