# Customer portal demo

1. Start Credit Desk using the existing launcher.
2. Sign out, open **New customer? Create an account**, then create a customer account.
   Administrators can also create a user with the **Customer** role in User management.
3. Sign in as the customer. Click the circular profile button beside **Credit Desk** at the top
   of the sidebar to open **My profile** and save the name, contact details and location.
   Choose a JPG, PNG or WebP photo (up to 5 MB), edit your details and press **Save my profile**.
   The single save button stores the personal details and photo together.
   The saved photo appears in My profile and in the circular sidebar button. Images
   are validated, cropped to 512 x 512 and saved privately without original metadata.
4. Submit a loan from **Loan requests**. It starts as **Pending review**.
5. Sign out and sign in as an employee. Open **Decisioning → Customer requests**.
   Approve or decline the request with a customer-visible explanation. Approval records
   the approved amount, annual interest and term; it does not issue funds.
6. After approval, select **Approved**, choose the request, and record the issue of money
   with its issue date and first payment date. This creates one loan in the existing Loan book
   and links it to the customer's account. This button records a demo transaction;
   it does not transfer money through a payment provider.
7. Employees record repayments in the existing **Loan book**. Customers can sign in
   again or press **Refresh my records** to see their balance, schedule, payment history
   and reminders (due within seven days or overdue).

An employee may also link an older loan under **Customer requests → Link an existing loan**,
after verifying ownership. Names are never automatically used to claim loans. A loan can
only be linked once. Customers cannot access employee pages or choose another customer's
account. Internal collection notes and employee risk information are not shown in the portal.

Notifications are inside the portal; this version does not send email/SMS or collect payments.
**My loans & payments** shows completed installments, principal repaid and interest paid.
Payment history separates principal and interest for every payment. Under **Payment receipts**,
select a payment and press **Download receipt (PDF)**. Receipt references use the saved payment ID;
the customer must own the loan to obtain a receipt. All customer money displays use two decimals.
The bell in the top-right corner opens Notifications. Its red badge counts unread request,
decision, loan and due-payment updates. Opening Notifications marks the displayed updates
as read; this is saved per account and survives signing out. The badge is hidden at zero.
Loan amounts use the project's existing dollar currency. Principal remaining excludes future
interest and is not a payoff quote. Loan book's existing restructuring and settlement conventions
still apply. Customer requests issued by employees without model scoring have an **Unrated**
risk band (existing economics uses its conservative fallback assumption).

Customer profiles, requests and loan links live in additional tables in the existing audit SQLite
database. Passwords continue to use the existing account store. Keep these local data files out
of GitHub; use persistent hosting storage if records must survive hosting restarts.

## Support, statements, cancellation and phones

- **Customer support** in the customer menu lets customers open a private question, optionally
  select one of their own loans, and follow replies under **My conversations**. Employees use
  **Decisioning → Customer support** to reply and mark conversations resolved. A new reply
  reopens a resolved conversation. Staff replies create an unread bell notification for the owner.
  These are messages within the website; no email or SMS is sent.
- **My loans & payments → Download loan statement (PDF)** exports the selected loan's current
  summary and complete payment history, with principal, interest, balance, and next payment.
  A customer cannot export another customer's statement.
- A pending request has **Cancel request** in its history card. Once reviewed, it cannot be
  cancelled. Cancelled records remain visible in both customer history and the employee's
  **Cancelled** filter. Cancellation and review use the same database write lock, so a stale
  employee review cannot approve a request that has just been cancelled.
- On phones, the menu starts collapsed, cards and form columns stack vertically, tabs can scroll,
  and controls have larger tap areas. Tables scroll inside their own area rather than widening
  the whole page. Desktop layout keeps its columns.


## Account, payment and storage improvements
- Customer registration provides a private recovery code; My account can replace it after password confirmation.
- Forgot password accepts a saved single-use recovery code. MFA remains enabled.
- Loan applications display a 10% flat-interest estimate, rounded monthly/final payments and total repayment before submission.
  Staff approval determines final terms; the estimate is not automatic approval.
- Customers can report a payment reference, date and amount. Staff confirm/reject; only confirmation records a ledger payment.
- CREDIT_DESK_DATA_DIR supports a mounted persistent disk. See PERSISTENT_STORAGE.md for activation and migration.


## Loan details, calendar and application confirmation
- Loan details is a customer-only page with owned-loan terms, dates, progress and statement download.
- The monthly payment calendar shows paid (green), overdue (red) and upcoming (blue) due dates with text labels and amounts.
- Preview loan request opens a review step; only Confirm and submit writes the request. Back to edit preserves inputs.
- Each request history item has a downloadable PDF confirmation with its reference and submission date; this is not approval or a payment receipt.


## Customer dashboard, languages and phones
- Home prioritizes remaining principal, overdue amount, next scheduled payment and latest request.
- Request details brings the owned application, contact details, documents and decision into one page.
- Language / ភាសា selects English or Khmer and saves the preference per account. User-written content is not translated; PDF exports remain English.
- On phones, forms/buttons stack, inputs use readable sizes, payment tables become labeled cards, the calendar fits the screen, and dialogs can scroll.
- Customer-facing dates use DD/MM/YYYY and money uses USD with two decimal places.


## Customer self-service guidance
- Repayment schedule PDF downloads appear in Loan details and My loans & payments. They use the same owned-loan schedule, cent rounding and payment allocation as the portal.
- Before you apply lists required profile information and explains amount/term/purpose, preview confirmation and optional/requested supporting documents. Existing submission requirements are unchanged.
- Empty request, loan, payment and notification pages explain next steps and link to requests or Help / FAQ.
- Customer-only Help / FAQ answers application, interest-method, rounding, status, payment verification, downloads, cancellation, chat expiry and recovery questions in English and Khmer.


## Usability polish
- Payment calendars filter by status and search installment number, due date or amounts; month choices include only matching installments.
- Profile completion counts the three required fields (name, phone, address). Optional email/photo do not reduce the score.
- Profile saves, request submissions and document uploads show a persistent dismissible success panel and a one-time toast after the write succeeds.


## Saved estimates, approved offers and drafts
- Confirming a new request stores the customer's reviewed flat rate and server-calculated interest, total repayment, monthly and final payment in the same transaction as the request. The receipt includes this estimate.
- Customer history/details and the staff review page show the saved estimate beside approved terms, labeling annual reducing-balance versus total flat interest explicitly. Older requests show that no estimate was saved; none is invented.
- Application fields autosave per authenticated customer after a field edit is committed. Save draft is also available. Returning restores amount, term, rate, product and purpose; Discard draft removes it. No profile or approval is needed merely to save a draft.
- Successful submission clears the saved draft atomically; it remains separate from loan requests until the customer confirms submission.


## Customer messaging portal (staff portal deferred)
- Messages contains All messages, Unread and Payment notices, with saved conversation previews and account-scoped unread counts.
- Customers send messages to the existing staff inbox and read real staff replies. Linked-loan conversations keep the loan reference visible.
- System overdue notices derive current unpaid installments; Discuss this payment opens an existing open loan conversation or starts a new linked message. They are labeled system notices, not staff contact.
- Customer messages show Sent/Seen based on the staff read position. Bot acknowledgements do not count as staff replies.
- Notifications and loan details link to customer messaging. No separate staff portal, external messaging service, or new outbound staff-contact workflow was built in this step.
- Existing 24-hour chat expiry/deletion policy remains in effect; archival retention was discussed but not approved.


## Undo
- Signed-in pages have a fixed top-left Undo control. It reverses the latest newly recorded supported action for that account, with an audit entry and conflict checks.
- Supported: own saved profile/photo, application draft changes/discard, pending request submission (cancel and restore draft), pending request cancellation (reopen), unreviewed uploaded request document (withdraw), own sent chat message (withdraw).
- Sent messages and uploaded documents are not physically erased by Undo; conversation/document views show a withdrawal or hide the withdrawn attachment. Original records remain subject to existing retention/backup policy.
- Reviewed/issued loan requests, approved offers, confirmed payments, passwords, permissions and other users' records cannot be rolled back by this control. Navigation/filter changes are not part of the saved-action history.
- Undo history begins with new actions after this update. A stale action is blocked rather than overwriting newer data. Staff can undo their own profile edits and chat sends; financial decisions remain protected.
