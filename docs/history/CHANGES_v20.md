# Credit Desk v20 — changes

Built on v19 (v18 + browser hosting). No change to the model, the data, the policy rules or the
database layout; existing `data/*.db` files keep working.

## 1. Late-payment notification moved to where it is seen
* **Before:** a red card in the sidebar, squeezed between the menu and the user panel, plus a
  pop-up toast once per sign-in.
* **Now:**
  * a slim **alert bar across the top of every page** (except Loan book, whose first tab is the
    full list): number of customers late, amount overdue, coloured chips per level
    (default / serious / warning / reminder) and a red **Open late payments →** button;
    **✕** hides it for the rest of the session;
  * a red **"N late" badge on Loan book** in the menu, always visible;
  * the amber variant appears when no one is late but payments are due in the next 3 days;
  * the toast was removed (the bar replaces it).
* Code: `app.py` (`_late_status`, `_late_banner`, `render_nav(..., late_customers=)`), styles in `src/ui.py`.

## 2. Portfolio filters look like the menu groups
* "Portfolio filters" is now a collapsible header with the same style as **▾ Portfolio**,
  **▾ Decisioning**, **▾ Account**. Click it to fold the filters away; the chosen filters are kept
  and the header shows "(2 on)" when filters are active.
* The signed-in user, Sign out and the source/version footer moved to the bottom of the rail.

## 3. Loading screen before every receipt
* After **Save record** (payment, promise, note, settlement, restructure, write-off), **Create loan**,
  **Save decision**, review **Approve / Reject / Return**, and policy **Submit / Approve / Reject**,
  a short full-screen "Saved. Preparing your receipt..." screen appears, then the receipt window opens.
* Code: `views/_result.py` (`_loading_screen`, called by `push`).
* Fixed: "Last promise: nan" on the late-customer card now reads "none".

## 4. Score an application starts empty
* Every field starts blank (no made-up 5,000 income or 700 score). The officer types each value.
* Required: monthly income, dependents, loan amount, term, product, credit history, employment,
  property area, credit score, late payments. Optional (blank = 0): co-applicant income,
  existing monthly debt, collateral value.
* Until every required field is filled, the page shows a progress bar ("7 of 10 required fields
  filled in") and the list of what is still missing; the score and Save appear after that.
* **Fill with an example** puts in a practice applicant (for training and demos);
  **Clear form** empties everything again.

## 5. Document type is detected automatically
* The **Document type** drop-down is gone (Score an application, Decision queue, Loan book).
  Choose a file → the type is read from the file name (and, for a PDF, its text) → a green line
  shows "Document type detected: Identity · the file name contains "identity"" → **Attach as Identity**.
* Keywords: identity / passport / ID card → Identity; income / payslip / salary → Income proof;
  bank statement / statement → Bank statement; collateral / valuation / appraisal / land title →
  Collateral / valuation; contract / agreement → Contract; anything else → Other.
* The upload box now says 10 MB (it said 200 MB; files over 10 MB were always refused).
* Code: `src/documents.py` (`detect_kind`), `views/_docs.py`, `.streamlit/config.toml` (`maxUploadSize = 10`).

## Tests
* `tests/test_v20.py` (21 new tests); `tests/test_pages.py` fills the form with the example first.
* Full suite: **216 passed**.
