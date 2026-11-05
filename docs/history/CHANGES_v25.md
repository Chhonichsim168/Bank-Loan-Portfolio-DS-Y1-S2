# v25 - Email accounts and Sign in with Google

## Sign-in page (src/auth.py)
* One card: Sign in and Sign up buttons side by side, "Forgot password?" under the password; Sign up and Forgot password swap the card (with Back to sign in). Reset by email code signs the person straight in. In trial mode without an email sender the code is shown on screen.
* **Continue with Google / Sign up with Google** (Streamlit `st.login("google")`, OpenID Connect) when
  `.streamlit/secrets.toml` has `[auth]` + `[auth.google]` and Authlib is installed.
* Sign in with **username or email**.
* Create account asks for **email** (required) and an agreement tick; with email sending set up, a
  6-digit code verifies the address (step 2), otherwise the recovery code is shown as before.
* Forgot password: Google users are told they have no password to forget; with email sending set
  up, a 6-digit reset code by email (same answer whether or not the address exists); otherwise the
  saved recovery code (username or email accepted).

## Accounts
* Every account can hold one unique email; "verified" when proven by Google, by an emailed code, or
  entered by an Administrator.
* Google sign-in: verified email -> that account; otherwise a new account - Administrator if listed in
  `CREDIT_DESK_ADMIN_EMAILS`, else Customer. An unproven claim on the same address by another account is
  released (prevents pre-registering someone else's Gmail).
* Google-only accounts have no password; they can add one in My account.
* Email codes: only a hash is stored, 15-minute expiry, 5 tries, 60-second resend wait, single use.
* Signing out also ends the Google session.

## Pages
* **My account**: summary card (email + Verified badge + sign-in methods), change email (password
  confirm), verify with Google or by email code, set/change password, MFA, recovery code.
* **User management**: Email and Sign-in columns; add a user with an email or as Google-only; change a
  user's email (counts as verified).
* Customer **My profile** email is prefilled from the account email.

## Other
* `src/mailer.py` (SMTP, Gmail App password, branded HTML code email).
* `launch.py` warns when port 8501 is busy (Google only accepts the registered address); Authlib added
  to requirements; `.streamlit/secrets.toml.example` documents `[auth]`, `[auth.google]`, `[email]`.
* Tests: `tests/test_v25_email.py`; two older tests updated for the new sign-in labels.

## Customer portal redesign (views/portal.py)
* The old customer pages (views/customer.py, loan_details.py, request_details.py, customer_help.py) are
  replaced by ten pages: My dashboard, Pay (KHQR demo + pay-off calculator + ask for help), Repayment
  schedule (colour calendar + table + PDF/CSV), Apply for a loan (calculator, budget check, tracker,
  documents), Messages, My documents, Notifications, Profile & security (sign-in history), My account, Help.
* All data comes from the same SQLite tables as the staff pages, filtered by the signed-in customer.
* Staff see "customer payment(s) received online today" at the top of every page.
* src/sample_customers.py: Chhonich Sim (chhonichsim1@gmail.com, late) and Cich Sim (cichsim@gmail.com,
  on time), password customer123, created on start when missing.
* qrcode added to requirements. Tests: tests/test_customer_portal_ui.py rewritten for the new portal.

## Real KHQR, staff-opened accounts, four-eyes for customer loans
* src/khqr.py: dynamic KHQR built from the bank's own receive-money QR (CRC-16 verified against the ABA
  QR), Bakong Open API `check_transaction_by_md5` (token in secrets, no relay server). Pay page: real QR,
  automatic check every 5 s (max 60), "check now", and "ask the bank to confirm" (staff verification).
  `test_amount` charges a small amount while recording the full one. Demo mode stays when not configured.
* Customer requests > "Accounts for existing loans": Administrator / Risk Manager opens the customer's
  account with their email, links the loan(s) and emails the sign-in details. Linking is now limited to
  Administrator / Risk Manager.
* Four-eyes rule for customer requests: after the first approval a different Risk Manager or Administrator
  must give the second approval before the loan can be issued (off only in single-operator mode).
* Fix: sample customers no longer stop the trial staff accounts from being created on a fresh install.

## Polish (everything from the usability review)
* Phones: "START Credit Desk ONLINE" (launch.py --online) starts an ngrok tunnel on the fixed domain in
  CREDIT_DESK_PUBLIC_DOMAIN and switches the Google redirect URI; a quick-navigation bar on narrow screens.
* Pay: "Save QR to my phone" (scan from the gallery). src/qr_payments.py remembers every real QR and re-checks
  open ones with Bakong when the customer comes back or staff open a page; one shared, double-safe recorder.
* Staff: "payment(s) waiting for your confirmation" alert with a link, auto-refresh every 30 s.
* src/notify.py: due-in-3-days and overdue reminders, payment received, request decisions, loan linked,
  payment report reviewed - each email sent once (customer_email_log).
* Google sign-in clears the one-time-password step; "late fees" wording fixed; Khmer for all portal text.
* User management: Linked loans column, link loans when creating a customer, link more, resend sign-in email.

## Reports page (full export)
- New **Portfolio → Reports** page (`views/reports_page.py`, `src/report_center.py`): pick a period and sections,
  download one Excel workbook (Summary, Loans with customer contact, Payments with channel and Bakong hash,
  Late customers with follow-up and last contact, Upcoming dues, Customer requests with four-eyes approvers,
  Decisions, Vintage, Roll rates, Customers, Support, Emails sent, Audit log) and/or a PDF summary with charts.
- Customer accounts and the Audit log are limited to Risk Manager / Administrator. Read-only; every export is audited.
- Tests: `tests/test_report_center.py`. Guide: `REPORTS (Khmer).md`.
