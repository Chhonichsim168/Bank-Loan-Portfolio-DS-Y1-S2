# Credit Desk v23 — the applications live in SQLite

Built on v22. **The data is not changed**: the same 2,000 applications, the same 12 columns, the
same values. Only where they are kept changed.

## What changed
* On first start, `data/loan_data.csv` is imported once, value for value, into the SQLite table
  **`applications`** in `data/audit_log.db`. From then on every analysis page, KPI, chart and the
  model read the table, not the CSV. (The CSV stays in the project as the original source.)
* Checked by the tests: the frame read back from SQLite is identical to `pd.read_csv` of the file,
  the cleaned book is identical, and the model version is identical - so AUC stays **0.856**.
* New page **Portfolio > Application data**:
  * **Browse and remove** - every record, newest first, filters, find by ID, download CSV;
    tick rows (or type IDs), give a reason, confirm, **Remove** (Risk Manager / Administrator).
  * **Add a record** - a past application and its outcome (all 12 fields, same validation rules
    as Score a file). Every role can add.
  * **Removed records** - the archive: who removed what, when and why.
  * A receipt (with PDF) after every add / remove, like the rest of the system.
* **Charts update automatically**: the page cache is keyed on the table's change counter, so the
  next page view after an add or remove uses the new data (Overview shows 2,001 of 2,001 ...).
  The model is re-trained for the new data on first use (about 15 s); going back to the original
  2,000 records reloads the saved original model instantly.
* Safety: every add / remove is written with a hash-chained audit entry (Activity log shows
  "Application record added / removed"); a removal that would leave fewer than 500 records or only
  one outcome is refused.
* Data and governance > Data source: loading an extract or reverting to the bundled sample now
  re-imports it into the table (this replaces records added by hand - the page says so).

## Files
* new `src/app_store.py`, `views/appdata.py`, `tests/test_v23.py` (16 tests)
* `src/state.py` (book read from SQLite, content-hash fingerprint), `src/data_pipeline.py`
  (`run_pipeline` also accepts the frame from the database), `app.py` (menu), `views/governance.py`.
* Full suite: **249 passed**.
