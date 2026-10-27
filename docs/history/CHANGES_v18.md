# v18 - late-payment notifications and result slips

Nothing existing was removed; these are additions.

## Late-payment notifications
- **Sidebar alert on every page** (all roles): how many customers are late, the amount overdue and how
  many are at each level, with a link to the list. Recomputed only when a loan or payment is added.
- **Pop-up reminder** once after each sign-in when someone is late.
- **Loan book > Late payments** (new first tab): every active loan with an unpaid instalment, most urgent
  first - level (Reminder 1-29 days, Warning 30-59, Serious 60-89, Default 90+), days late, overdue
  amount, unpaid instalments, last payment, last promise to pay and what to do. Open a customer to
  download an **overdue notice letter (PDF)** or record a payment / promise / note on the spot.
- Logic: `src/notifications.py` (pure functions, tested).

## Result window ("invoice") after important buttons
A pop-up window opens with the result laid out like an invoice - number, Phnom Penh date and time,
key facts, what happens next - plus a **PDF slip** to print or send:

| Button | Window | PDF |
|---|---|---|
| Score an application > Save decision | Decision saved | Decision slip + full record + customer letter |
| Loan book > Add a loan > Create loan | Loan created | Loan disbursement statement with schedule |
| Loan book > Save record (payment) | Payment receipt (no. PAY-000123) | Payment receipt |
| Save record (settle / promise / note / restructure / write-off) | Matching slip | Matching slip |
| Decision queue > Approve / Reject / Return | Review recorded | Second approval result |
| Policy > Submit proposal, Approve, Reject | Policy change result | Policy change slip |

Code: `views/_result.py` (window), `src/reports.py` (`receipt_pdf`, `overdue_notice_pdf`).
`loanbook.add_event` now returns the record number used on receipts.

Tests: `tests/test_v18.py` (11 new; 195 in total).
