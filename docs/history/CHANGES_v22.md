# Credit Desk v22 — late-payment follow-up, Paid button, new-record dots

Built on v21. Only the features below changed.

## 1. "New record" dot on Loan book > Loans
* When a record (payment, promise, note, ...) is saved on a loan - from any tab - the loan gets a
  blue dot until you open it: the tab reads **Loans 🔵 2 new**, the table has a **New** column
  (🔵 + number of new records, those loans listed first), the "Open a loan" list shows
  `🔵 LN-... - 2 new record(s)`, and the opened loan shows "🔵 Updated". Opening the loan clears it.
* Per user, stored in the new table `loan_seen` (`src/loanbook.py: unseen_loans, mark_seen`).
  Records saved before your first visit to Loan book never count as new.

## 2. Supporting documents removed from Loan book and Decision queue
* Still available on Score an application (unchanged).

## 3. Late payments: one history, follow-up tags, Paid
* The Late payments tab now shows the customer's **History** (newest first) right above the
  record form - the same records as Loans > that loan > History, whichever tab saved them.
* **Follow-up tag** on every late customer (table column, customer list, customer card, counts):
  `Promised - not paid yet`, `Contacted - not paid yet` (note), `Part-paid - still overdue`,
  `Not contacted yet`. A promise or note **never** takes the customer off the list or out of the count.
* **payment** reduces the overdue amount; the customer leaves the list when it is fully covered.
* **✅ Paid** button on top of the history (Late payments tab and Loans tab): confirms and records a
  payment of exactly the overdue amount, today, prints the receipt, and the customer leaves the
  late list (the "N late" badge goes down by one).

## Tests
* new `tests/test_v22.py` (7 tests). Full suite: **233 passed**.
