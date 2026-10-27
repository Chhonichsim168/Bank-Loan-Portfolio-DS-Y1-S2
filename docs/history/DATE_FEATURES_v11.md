# Credit Desk v11 — date tracking

Every application now carries the day it was received, and every page that benefits from time
shows it. Dates are **never** a model input. Times are stored in UTC and shown in Phnom Penh time
(UTC+7). Full suite: 160 tests pass (39 new in `tests/test_dates.py`).

## Data
- `data/loan_data.csv`: new `application_date` column, 2,000 applications from Jan 2024 to Sep 2026
  (weekdays only, growing volume, Khmer New Year dip in April, year-end peak). Approval labels and
  every other field are unchanged.
- `data/application_sample_100.csv`: dates 1–16 Oct 2026.
- Pipeline validates dates (not a date / in the future / before 2000 → rejected) and derives
  `application_month`, `application_quarter`, `application_year`, `application_weekday`.
- Extracts without dates still load; date features hide themselves.

## Where each date feature lives
| Page | What was added |
|---|---|
| Sidebar (all analysis pages) | **Period** filter: All time, Latest month, Last 3/6/12 months, Year to date, Previous calendar year, Custom range |
| Overview | KPIs compared with the previous period of equal length; **Monthly trend** chart with the period shaded; year-to-date vs last year line |
| Segments | Break down by application quarter, year and day of the week |
| Approval drivers | **Have the drivers changed over time?** — correlation per year |
| Loan book | **Payments due soon** (arrears first, then 7/14/30 days), maturing within 3 months, maturity date, months on book, instalments left; Phnom Penh "today" |
| Score an application | **Application received** date; **repeat applicant** history for the same customer reference |
| Score a file | Optional `application_date` column; chart **by day received**; warning for rows waiting > 3 days |
| Policy and cut-offs | **Month by month** impact of the draft rules; **version timeline** (in force from / until / days); local times |
| Decision queue | Received date, days to decide, **days waiting**, > 2-day SLA alert (oldest first), date range filter, decisions per week, local time |
| Model performance | Out-of-time validation now runs (oldest 75% train / newest 25% test); **Stability over time** tab with AUC per quarter |
| Data and governance | Applicant-mix drift: any quarter vs everything before it; fairness ratio **year by year**; activity log with date range, user filter and events per day |
| User management | Last sign-in, days since sign-in, password age; inactive (> 90 days) accounts flagged |
