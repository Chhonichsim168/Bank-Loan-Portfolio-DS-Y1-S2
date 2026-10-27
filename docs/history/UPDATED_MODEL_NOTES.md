# Credit Desk — New Dataset Model Update

## Dataset used
`data/loan_data.csv` now uses the supplied 2,000-row dataset with these 11 fields:

- applicant_income
- coapplicant_income
- loan_amount
- loan_term_months
- credit_history
- dependents
- employment_status
- property_area
- credit_score
- late_payments_12m
- approved (target)

## Model changes
The previous model did not use `credit_score` or `late_payments_12m`. The new model uses every available predictor and adds history/affordability features:

- credit_score_band
- late_payment_rate
- credit_payment_stress
- income_per_dependent
- loan_burden_x_credit
- total_income
- loan_to_income_ratio
- loan_to_annual_income
- estimated_emi
- debt_to_income_ratio
- household_size

The predictor set never uses `approved` as an input feature, avoiding direct target leakage.

## Prediction model
A soft ensemble is used:

- 75% Logistic Regression — interpretable linear component
- 25% Gradient Boosting — captures non-linear relationships and interactions

The final probability is the weighted average of the two probabilities.

## Validation
On the supplied dataset, the current 25% stratified hold-out produced:

- Accuracy: 0.786
- Precision: 0.782
- Recall: 0.826
- F1: 0.804
- ROC AUC: 0.862

Five-fold stratified cross-validation produced mean ROC AUC ≈ 0.851, which is a better stability check than relying on one split.

These metrics describe this dataset and validation setup; they are not a guarantee of future lending performance.

## Fix: credit score and late payments pointed the wrong way
**Symptom:** raising "Late payments — last 12 months" *increased* the approval probability, and
a higher credit score could lower it.

**Cause:** `credit_history` is almost a summary of score + late payments in this dataset. In an
unconstrained model it absorbed their signal, leaving the standardized weights of `credit_score`
(−) and `late_payments_12m` (+) with the wrong sign through multicollinearity.

**Fix (`src/risk_model.py`):**
- Logistic part replaced by `SignConstrainedLogistic`: credit score / history can only help;
  late payments, DTI, EMI, loan-to-income, payment stress can only hurt.
- Gradient boosting part switched to `HistGradientBoostingClassifier` with the same
  `monotonic_cst` directions.
- `credit_score` and `late_payments_12m` have a minimum standardized weight of 0.30 (`MIN_EFFECT`)
  so they stay visibly influential.

**Result (example applicant, $5,000/mo, $120K loan):** late payments 0 → 8 now moves approval
66.1% → 36.2%; credit score 300 → 850 moves it 40.5% → 74.4%. Hold-out ROC AUC 0.858
(was 0.862); 5-fold ROC AUC 0.849 (was 0.851). Hold-out accuracy 0.786.
Regression tests added at the end of `tests/test_decisioning.py`.
