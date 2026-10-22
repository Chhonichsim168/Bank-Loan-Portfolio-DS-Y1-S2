# Credit Desk

**Loan portfolio analytics and decisioning console.** A credit officer scores an
application and gets the reasons behind it. A risk analyst finds where the book
concentrates. A policy manager changes a cut-off and sees what it would have cost.

Built with Python, pandas, scikit-learn and Streamlit.

![Python](https://img.shields.io/badge/Python-3.10%2B-1B2430)
![Streamlit](https://img.shields.io/badge/Streamlit-1.40%2B-0B6B62)
![Tests](https://img.shields.io/badge/tests-195%20passing-1F7A5C)
![License](https://img.shields.io/badge/License-MIT-5B6879)

---

## How to open (first time and every time)

**1. Get the project.** On GitHub click **Code → Download ZIP**, then right-click the ZIP and
choose **Extract All** (or use `git clone`).

**2. Double-click the START file** inside the folder:

| Computer | File to double-click |
|---|---|
| Windows | `START Credit Desk (Windows).bat` |
| Mac | `START Credit Desk (Mac).command` (first time: right-click → **Open** → **Open**) |

The first start installs everything it needs by itself (Python too, on Windows 10/11, if it is
missing) — this takes about 2–5 minutes and needs internet. Later starts take a few seconds.

**3. The browser opens Credit Desk.** Sign in with `admin` / `admin123`.
Keep the black window open while you use the app; close it to stop.

> **ខ្មែរ — របៀបបើក៖** ① ទាញយក ZIP ហើយ Extract ② ចុចពីរដងលើ `START Credit Desk (Windows).bat`
> (ឬ `(Mac).command`) — លើកដំបូងវាដំឡើងអ្វីៗទាំងអស់ដោយខ្លួនឯង (2–5 នាទី ត្រូវការអ៊ីនធឺណិត)
> ③ Browser បើកឡើងដោយខ្លួនឯង → ចូលដោយ `admin` / `admin123`។ កុំបិទផ្ទាំងខ្មៅពេលកំពុងប្រើ។

<details>
<summary>Problems on first start?</summary>

| You see | Do this |
|---|---|
| "Windows protected your PC" | Click **More info → Run anyway** |
| Mac: "cannot be opened because it is from an unidentified developer" | Right-click the file → **Open** → **Open** |
| "Python could not be installed automatically" | Install Python from python.org, tick **Add python.exe to PATH**, double-click START again |
| "Installing packages failed" | Check the internet, then double-click START again |
| The browser did not open | Open the address shown in the black window (usually `http://localhost:8501`) |
| Want to start from an empty system | Close the app, delete `data/audit_log.db` and `data/sample_data_loaded.txt`, start again |

Manual start for developers: `python launch.py`, or
`pip install -r requirements.txt` then `streamlit run app.py`.
</details>

### Put it on the web

Free hosting on **Streamlit Community Cloud** straight from this GitHub repository (main file
`app.py`, Python 3.13) - step by step, with safety settings, in `HOW TO HOST.md`.

### New in v18

- **Late-payment alert** in the sidebar on every page, a reminder after sign-in, and a
  **Loan book > Late payments** tab with an overdue notice letter (PDF) for each late customer.
- **Result window with a PDF slip** after every important button: Save decision, Create loan,
  Save record (payment receipt), Approve / Reject / Return, and policy changes.
  Details: `docs/history/CHANGES_v18.md`.

### Accounts

No API key needed. Three simple accounts are created on first start:

| Username | Password | Role |
|---|---|---|
| `admin` | `admin123` | Administrator - every page, user management |
| `risk` | `risk123` | Risk Manager - policy, model, governance, second approvals |
| `officer` | `officer123` | Credit Officer - scoring and saving decisions |

A wrong password is refused and recorded in the audit log, but **never locks the account**, and
new passwords only need 4 characters. Create more people under **Administration -> User
management**. State (users, audit log, decisions, policy versions, models, uploaded extracts) is
created under `data/` on first use.

Options (remove `rem ` / `# ` in front of a line in the START file, or set them in the environment; see `src/mode.py`):

| Setting | Effect |
|---|---|
| `CREDIT_DESK_REQUIRE_LOGIN=0` | No sign-in at all; one person approves their own cases |
| `CREDIT_DESK_LOCKOUT=1` | Lock an account for 15 minutes after 5 wrong passwords |
| `CREDIT_DESK_STRONG_PASSWORDS=1` | New passwords need 12+ characters and mixed character types |
| `CREDIT_DESK_DEMO_USERS=0` | First start creates one `admin` with a random one-time password instead |

Optional:

```bash
python src/data_pipeline.py    # data-quality audit, writes data/loan_data_clean.csv
python generate_report.py      # standalone HTML report with every chart embedded
pytest -v                      # 195 tests (about 3 minutes; trains the model several times)
```

---

## What it does

### Portfolio

**Overview** — approval rate, exposure, risk concentration and affordability, each measured
against the whole book so a filter that changes nothing looks like it changed nothing.
Includes a preview of the exceptions queue.

**Segments** — cut the book by any dimension, or by area × employment × risk. Every segment
is ranked by how far it sits from the book average, with a minimum-size control so small
segments do not masquerade as findings.

**Approval drivers** — what actually moves the decision, ranked by strength of association,
with the affordability curve that shows where approval gives way.

### Decisioning

**Score an application** — the page the product exists for. Scores live as you type, then
shows:

- routing band (fast-track / review / refer / decline) against the current cut-off
- affordability read-out with policy bands drawn, not described
- **reason codes** - Shapley attribution of the final score by business factor; with the typical-applicant baseline they add up exactly to the score shown
- **hard policy** applied exactly as on Score a file, and a warning when inputs are outside the model's training range
- **sensitivity** — the same application re-scored under changes an officer could actually
  discuss ("reduce loan by 25%", "add a co-applicant")
- **comparables** — what the book historically did with applications like this one
- **Save decision**: writes a database record (application ID, officer, inputs, reasons, score range, policy and model versions) with a downloadable record and, for declines, a draft adverse-action notice

**Score a file** — upload a day's intake as CSV, get every application scored, routed and
checked against the same policy and routing as the single-application page. Every row is validated first - a row with a missing, non-numeric, out-of-range or unknown value is not scored and is listed with its row number and reason. Limits: 20 MB / 50,000 rows. The file itself is scored in memory and not stored; the run is logged.

**Policy and cut-offs** — three things a lending policy team needs:

- *Underwriting rules*: change the DTI cap or affordability multiple and see how much volume
  it blocks, how much good business it blocks with it, and which rule is doing the work
- *Model cut-off*: bad-business-let-through against good-business-turned-away, scored
  out-of-fold so the trade-off is the one you would actually get
- *Exceptions queue*: every breaching application, ordered by exposure at risk, exportable

### Governance

**Model performance** — discrimination (ROC, confusion matrix), **calibration** (does a 70%
score mean 70%?), coefficient weights, and **per-segment AUC** — the first check a
fair-lending review runs.

**Data and governance** — lineage with the validation rules and their results, field
definitions, the risk-scoring rule written out in full, an honest account of what the system
does not know, and an uploader to point the app at a different extract.

---

## Design

The visual system is documented in [`docs/design_system.md`](docs/design_system.md). The
short version:

- **One recurring idea.** Credit risk is the study of where a number crosses a line, so the
  signature component is a *band rail*: policy thresholds drawn as segments with a marker
  for where this value sits. It appears under KPIs, beside every DTI figure and in the
  decision banner. One idea, used consistently, learned once.
- **Deep teal, not navy-and-gold.** Risk colours are deliberately desaturated. Traffic-light
  saturation is for dashboards that want to look urgent; a credit book wants to look
  measured.
- **One typeface.** IBM Plex Sans, drawn for enterprise data, with tabular figures
  throughout so digits do not shift width between rows of a loan table.
- **Comparison is mandatory.** A metric without a baseline is trivia.
- **Product language.** "Score an application", not "Applicant What-If Simulator".

---

## Project structure

```
app.py                      Shell: page config, theme, auth gate, nav rail, filters
src/
  data_pipeline.py          Load, clean, validate, engineer features
  analytics.py              Filtering, grouping, pivots, statistics
  risk_model.py             Calibrated ensemble approval model, model version, validation evidence
  decisioning.py            Shapley reason codes, sensitivity, hard policy, ONE routing rule, score range
  registry.py               Versioned, hash-checked model store (a past score can be reproduced)
  policy_store.py           Shared, versioned policy + cut-off + data source; propose/approve (four-eyes)
  workflow.py               Saved decisions, application IDs, second approval, append-only records
  monitoring.py             PSI drift, retrain trigger, back-test against real outcomes
  fairness.py               Adverse-impact ratio by group (and any protected column present)
  security.py               CSV formula-injection guard, filename sanitiser, HTML escape
  visualizations.py         Matplotlib charts for the standalone report
  ui.py                     Design tokens, stylesheet, Plotly theme, components
  state.py                  Cached loading and the shared filter context
  auth.py                   Login, lockout, MFA, idle timeout, user administration, roles
  audit.py                  Hash-chained, append-only audit log; fails loudly
views/                      One module per page
data/loan_data.csv          2,000 historical applications
data/users.json             Created on first run (never shipped, never committed)
Dockerfile, requirements.lock   Reproducible build; CI in .github/workflows
deploy/nginx.conf.example   Reverse-proxy config that terminates TLS in front of the app
docs/
  design_system.md          Design rationale and token system
  data_dictionary.md        Field-by-field reference
generate_report.py          Standalone HTML report
tests/                      103 tests
```

Nothing in `src/` imports Streamlit except `ui.py`, `state.py` and `auth.py`'s session
helpers, so the pipeline, analytics and decisioning layers run unchanged in a notebook or a
batch job.

---

## Access, audit and deployment

**Authentication.** Passwords are salted PBKDF2-SHA256 at 600,000 iterations (older hashes are
verified at their own cost and upgraded at the next sign-in). **No credential ships with the app** -
see Quick start for the first-run administrator. Five failed sign-ins lock an account for 15 minutes;
every failed, locked and blocked attempt is audit-logged. Sessions time out after 20 idle minutes
(`CREDIT_DESK_SESSION_MINUTES`). Multi-factor sign-in (TOTP; any authenticator app) is optional per user
and mandatory for everyone with `CREDIT_DESK_REQUIRE_MFA=1`. Administrators create users, change roles,
disable accounts and reset passwords/MFA on the **User management** page (the last active
Administrator cannot be removed); issued passwords are one-time and must be changed at first
sign-in. For single sign-on (Active Directory / OIDC), replace `auth.authenticate()` with an
identity-provider call - roles, timeout and audit stay as they are.

**Roles.** Credit Officers score applications and files, save decisions and follow their own cases.
Risk Managers additionally propose and approve policy, give second approvals and view model and
governance pages. Administrators additionally load data extracts and manage users. The permission
table is `PAGE_ACCESS` in `src/auth.py`.

**Policy is shared and versioned.** Rules, cut-off and the officer authority limit live in the database,
not in a browser session. A change is *proposed* with a written reason and takes effect only when a
*different* Risk Manager or Administrator approves it (set `CREDIT_DESK_SINGLE_OPERATOR=1` only for a
one-person team; self-approval is then recorded as such). Every decision stores the policy version it
was made under.

**Decisions are records, not downloads.** *Save decision* writes the full inputs, reasons, score and
range, routing, policy and model versions, the signed-in officer, and an application ID
(`APP-YYYYMMDD-XXXXXX`) to an append-only table, in the same transaction as its audit entry - no
audit record, no decision. Approvals require a verification checklist. A decision waits for a second
approver (not its author) when it is a referral, exceeds the officer authority limit, approves a
policy breach, overrides a decline-band score, or relies on inputs outside the model's training range.
The **Decision queue** page lists cases and records the second approval.

**Audit log.** `data/audit_log.db`; each row carries the hash of the previous one, SQLite triggers
refuse updates and deletes, and **Governance -> Activity log** re-verifies the whole chain and reports
the first altered record. A failed write raises (and is also written to `data/audit_fallback.jsonl`);
it is never swallowed. *Limit:* someone with full database access could rebuild the entire chain -
copy the newest hash shown on that page to a system the database administrator does not control, on a
schedule. Point `CREDIT_DESK_AUDIT_DB` somewhere outside the repo.

**Uploads and exports.** Uploaded extracts are validated in a private temporary folder that is deleted
afterwards, then stored under a hash-derived name (mode 0600); the user's file name is only a sanitised
label, and superseded extracts are purged (`CREDIT_DESK_RETENTION_DAYS`, default 90). Every CSV the app
produces neutralises spreadsheet formulas (`=`, `+`, `-`, `@`).

**Deployment.** The app binds to `127.0.0.1` only (`.streamlit/config.toml`) — it never
speaks TLS or listens on a public interface itself. A `Dockerfile` (non-root, `/app/data` as the one
writable volume, health check at `/_stcore/health`) and a CI workflow are included; publish the container
port only to the reverse proxy. `deploy/nginx.conf.example` is a
starting reverse-proxy config that terminates HTTPS with a real certificate and forwards
to the app over loopback; adapt the hostname and certificate paths for your environment.

---

## The affordability correction

Version 1 had a defect worth naming, because it changed every risk figure in the app.

Income in this dataset is recorded **monthly**. The derived `loan_to_income_ratio` is
therefore a multiple of monthly income, and its median is about 18x. The risk rule tested
that column against a threshold of `5` — which fired for **97.6% of the book**. A constant
dressed as a rule, silently adding a point to almost every applicant's risk score.

The fix derives `loan_to_annual_income` explicitly and tests against 3.5x, the conventional
retail benchmark. The tiers now separate properly:

| Tier | Share (before) | Share (after) | Approval rate (after) |
|---|---|---|---|
| Low | 59.5% | 68.4% | 69.2% |
| Medium | 34.6% | 28.4% | 19.8% |
| High | 5.9% | 3.3% | 1.5% |

A test now asserts the affordability flag fires on between 2% and 40% of the book, so this
cannot silently regress.

---

## Dataset

2,000 historical applications, one row per application, target `approved` (~53% / 47%).
Eleven source fields (ten application inputs plus the outcome, including `credit_score` and
`late_payments_12m`); the rest are derived on load. Full definitions in
[`docs/data_dictionary.md`](docs/data_dictionary.md) and on the Data and governance page.

To use your own extract, upload a CSV with the same eleven source columns on the **Data and
governance → Data source** tab, or replace `data/loan_data.csv`.

---

## Model

A soft ensemble - 75% sign-constrained logistic regression and 25% monotonic gradient boosting -
on all ten application fields plus derived affordability and credit-behaviour features, followed by
**Platt calibration fitted on out-of-fold scores** so that a displayed 70% behaves like 70% (the logistic
part is class-balanced, which on its own distorts probabilities). Credit score and late payments are
constrained so a better score never lowers approval and a late payment never raises it; calibration
keeps a positive slope so it cannot break that. See `docs/history/UPDATED_MODEL_NOTES.md`.

| Metric (hold-out / out-of-fold) | Score |
|---|---|
| ROC AUC (hold-out) | ~0.86 |
| AUC over 5 folds | ~0.85 +/- 0.01 |
| Expected calibration error | ~0.02 |
| Brier score | ~0.156 |

**Reason codes explain the number on the screen.** They are exact Shapley attributions of the *final*
score over nine business factors (income, loan amount, term, credit history, dependents, employment,
area, credit score, late payments) measured from a typical applicant; baseline plus the nine
contributions equals the displayed log-odds (asserted in the tests). Overlapping engineered columns (DTI,
instalment, loan-to-income...) are never shown as separate "reasons". A draft adverse-action notice lists
only the factors that worked against approval.

**Scores carry a range and a domain check.** The 90% range is the Wilson interval of how comparable
out-of-fold scores actually turned out. Inputs outside the values the model was trained on are flagged,
capped at *Refer* and need a second approver to approve.

**Models are versioned.** `data/models/<version>.joblib` + `.json`; the version hashes the training data,
features, constraints and hyper-parameters, the artefact hash is checked before loading, and every
decision records the model version.

Cut-off analysis uses **out-of-fold** predictions - every application scored by a model that never saw
it in training. Rows whose credit score, late-payment count or credit-history flag had to be filled in
are marked `*_imputed` and **excluded from training** (no score is not an average score).

---

## What this release fixed, and what it cannot

Fixed in code (each has a test): hard policy on *Score an application* (both pages share one routing
function); policy/cut-off/data source shared, versioned and four-eyes controlled; decisions saved at the
point of decision with IDs and the signed-in officer; tamper-evident audit that cannot fail silently;
no shipped credentials, lockout, MFA, idle timeout, user admin; batch validation row by row with
reasons; out-of-range warnings; reason codes that sum to the score; calibration, score range, model
registry; drift (PSI) and back-test tooling; adverse-impact screen; CSV-injection and upload hardening;
pinned dependencies, Docker, CI.

**Not solvable in code - these need your bank's data or decisions:**

- *Target = past approvals, not repayment.* Retraining on observed default/delinquency (PD) needs your
  performance data. Until then the model reproduces earlier judgement, biases included.
- *Out-of-time validation* needs an application date in the extract (the bundled file has none). If you
  add an `application_date` column the training code uses it automatically.
- *Fairness:* the data holds no protected attributes, so only proxy fields can be screened. Direct
  testing needs those attributes held separately from the model inputs.
- *Real data:* the 2,000-row bundled file looks synthetic. Use your own extract (Data source tab).
- *Expected loss / provisioning / IFRS 9 stage:* needs collateral (LGD), exposure and existing debts.
- *Risk-based pricing, products, KHR/USD:* the rate is a flat 8.5% assumption; contracted rates and
  product rules are yours to supply.
- *Bureau (CBC), core-banking, KYC/AML/sanctions and fraud checks:* need your integrations; the
  verification checklist records that a human did them, it does not do them.
- *Regulatory alignment (NBC classification/provisioning etc.):* have your compliance team confirm
  against current rules - this project makes no regulatory claim.
- *Encryption at rest, backups/DR, SSO:* infrastructure choices (encrypted volume, backup of `data/`,
  identity provider).

---

## Limits

This is a decision-support system. It is not an underwriting system, and the distinction is
not a formality:

- **The credit file is summarised, not full.** The data has a credit score and a 12-month
  late-payment count, but no tradelines, balances, inquiries, late-payment severity, or record
  of where the score came from. `credit_history`, `credit_score` and late payments overlap
  heavily, so they are not three independent signals; the model's credit fields are
  sign-constrained as a design decision, not something the data proved.
- **No collateral.** Loss given default cannot be estimated. This speaks to approval
  likelihood only, never to expected loss.
- **No existing liabilities.** Debt-to-income is computed from the requested loan alone.
  Treat every DTI figure here as a floor.
- **Interest rate is assumed** at a flat 8.5% p.a. for everyone. Risk-based pricing would
  change the instalment and therefore the DTI.
- **The target is the bank's past decision, not loan performance.** The model learns to
  reproduce historical underwriting, including its errors and any bias in it.
- **No fraud signal, no macro context, point-in-time.**

Before any operational deployment: join the full bureau report, use contracted rather than assumed
rates, retarget on performance rather than approval, validate out-of-time, document
fair-lending testing, and set a monitoring schedule with a defined retraining trigger.

---

## License

MIT. See [LICENSE](LICENSE).

## Added in v9 (all local - nothing leaves this computer)

- **Score an application**: existing monthly debts, collateral value and product; total-debt-service rule;
  suggested risk-based rate, instalment and expected loss; decision PDF and customer letter PDF; document attachments.
- **Loan book** page: loan creation from approved decisions, repayment schedule, payments, days past due,
  NPL, stages 1-3, vintage, roll rates, collections notes, promises to pay, restructure and write-off
  (Risk/Admin only), stress test, concentration and limit alerts, Excel/CSV export.
- **Policy page**: pricing, loss, default-probability assumptions and portfolio limits are under four-eyes change control.
- **Back-test** can use Loan book outcomes. **Model performance > Challenger** compares alternative models.
- **Data and governance > Backup and restore** (Administrator): passphrase-encrypted backup file.
- **Batch**: optional `existing_monthly_debt` and `collateral_value` columns; adds suggested rate and expected loss.

Limits: default probabilities and LGD are your assumptions, not model output; provisions are illustrative,
not regulatory; single currency; English UI (Khmer text in PDFs depends on the fonts installed); no external integrations.
Tests: 115 passing (`pytest`).
