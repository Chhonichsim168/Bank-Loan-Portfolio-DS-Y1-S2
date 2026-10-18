# Credit Desk v10 — system error fixes

Six calculation / logic errors fixed. Every fix has a regression test at the end of
`tests/test_decisioning.py` (`test_fix1` … `test_fix6`). Full suite: 121 passed.

| # | Error | Files | Before | After |
|---|-------|-------|--------|-------|
| 1 | Zero income gave DTI / loan-to-income = 0 ("no burden") | `src/data_pipeline.py` (`safe_ratio`, `NO_INCOME_RATIO`), `src/decisioning.py` (`_engineer_one`, `enrich_frame`, `apply_policy`) | $0 income scored 89%, passed every policy rule | Ratios set to 99 (far over every cap) + new hard rule **"No income"** → Decline, score 0.7% |
| 2 | DTI cap checked at a fixed 8.5% while the customer is charged up to 11.5% | `src/decisioning.py` (`Policy.assessment_rate`, `apply_policy`), `src/policy_store.py` (`Settings.policy`) | Instalment understated by up to ~29% | Caps checked at base rate + larger band spread (new columns `assessed_rate`, `assessed_emi`, `assessed_dti`) |
| 3 | Decline letter always said "A person reviewed this decision" | `src/decisioning.py` (`adverse_action_text`), `src/reports.py` (`customer_letter_pdf`), `views/underwrite.py` | Printed on every letter, including automatic declines | New `human_reviewed` argument (default False); the officer page passes True |
| 4 | Second approval only checked approvals that overrode the model | `src/workflow.py` (`review_requirements`) | An officer could decline a Fast-track/Review applicant unchecked | Such declines now need a second approver |
| 5 | Shorter loans scored far lower even at the same instalment | `src/risk_model.py` (`NOT_SCORED`, `SCORED_NUMERIC`, `MONOTONIC_DIRECTION`) | Same $922/month: 10-yr loan 41.7%, 30-yr loan 62.6% | Raw term no longer scored; loan size can only lower the score, income only raise it. Same instalment → ~60% for every term |
| 6 | `credit_payment_stress` capped at 10 for a single application but not in a file | `src/decisioning.py` (`_engineer_one`) | Single and batch could disagree | Identical formula everywhere |

Model metrics after the fixes (same data, same validation): hold-out ROC AUC 0.856 (was 0.858),
5-fold ROC AUC 0.842 (was 0.849). The small drop is the cost of removing the illogical term and
loan-size effects.

**After updating:** nothing to do. The model version id includes the new settings, so the app
trains and saves the corrected model by itself on first start (takes a few seconds). Decisions
saved earlier keep their old model version in their records.
