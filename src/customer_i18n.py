"""Customer-facing language and consistent status labels; stored per account."""
import re
import streamlit as st

KH = {
"My customer portal":"ផ្ទាំងអតិថិជន", "Home":"ទំព័រដើម", "Loan details":"ព័ត៌មានលម្អិតកម្ចី",
"Request details":"ព័ត៌មានលម្អិតសំណើ", "My profile":"ប្រវត្តិរូបខ្ញុំ", "My account":"គណនីខ្ញុំ",
"Customer support":"ជំនួយអតិថិជន", "Support chat":"ជជែកជាមួយក្រុមជំនួយ", "Notifications":"ការជូនដំណឹង",
"Sign out":"ចាកចេញ", "Sign in":"ចូលគណនី", "Username":"ឈ្មោះអ្នកប្រើ", "Password":"ពាក្យសម្ងាត់",
"Language":"ភាសា", "Customer":"អតិថិជន", "Loan requests":"សំណើកម្ចី", "My loans & payments":"កម្ចី និងការបង់ប្រាក់",
"My loans":"កម្ចីរបស់ខ្ញុំ", "Loan amount ($)":"ចំនួនប្រាក់កម្ចី ($)", "Term (months)":"រយៈពេល (ខែ)",
"Loan cost estimate":"ការប៉ាន់ប្រមាណថ្លៃកម្ចី", "Total interest · 10% flat":"ការប្រាក់សរុប · 10% លើប្រាក់ដើម",
"Monthly payment":"ប្រាក់បង់ប្រចាំខែ", "Total repayment":"ប្រាក់ត្រូវសងសរុប", "Request a loan":"ស្នើសុំកម្ចី",
"Loan product":"ប្រភេទកម្ចី", "What will you use the loan for?":"តើអ្នកនឹងប្រើប្រាក់កម្ចីសម្រាប់អ្វី?",
"Preview loan request":"ពិនិត្យសំណើមុនបញ្ជូន", "Review your loan request":"ពិនិត្យសំណើកម្ចីរបស់អ្នក",
"Confirm and submit":"បញ្ជាក់ និងបញ្ជូន", "Back to edit":"ត្រឡប់ទៅកែប្រែ", "Amount":"ចំនួនប្រាក់",
"Full name":"ឈ្មោះពេញ", "Phone number":"លេខទូរស័ព្ទ", "Phone":"លេខទូរស័ព្ទ", "Email (optional)":"អ៊ីមែល (មិនបង្ខំ)",
"Email":"អ៊ីមែល", "Location / address":"ទីតាំង / អាសយដ្ឋាន", "Location":"ទីតាំង", "Purpose":"គោលបំណង",
"Product":"ប្រភេទកម្ចី", "Term":"រយៈពេល", "Save my profile":"រក្សាទុកប្រវត្តិរូប", "Change photo":"ប្តូររូបថត",
"View profile photo":"មើលរូបថតប្រវត្តិរូប", "Profile photo":"រូបថតប្រវត្តិរូប", "No photo yet":"មិនទាន់មានរូបថត",
"Your profile has been saved.":"ប្រវត្តិរូបរបស់អ្នកត្រូវបានរក្សាទុក។",
"My request history":"ប្រវត្តិសំណើរបស់ខ្ញុំ", "Loan request tracker":"តាមដានសំណើកម្ចី", "Request status":"ស្ថានភាពសំណើ",
"Pending review":"កំពុងរង់ចាំពិនិត្យ", "Approved":"បានអនុម័ត", "Declined":"បានបដិសេធ", "Cancelled":"បានលុបចោល",
"All":"ទាំងអស់", "Paid":"បានបង់", "Overdue":"ហួសកំណត់", "Upcoming":"មិនទាន់ដល់កំណត់", "Active":"កំពុងដំណើរការ",
"Closed":"បានបិទ", "Written off":"បានលុបបំណុល", "Status":"ស្ថានភាព", "Search requests":"ស្វែងរកសំណើ",
"Search loans":"ស្វែងរកកម្ចី", "Search payments":"ស្វែងរកការបង់ប្រាក់", "Choose my loan":"ជ្រើសកម្ចីរបស់ខ្ញុំ",
"Loan status":"ស្ថានភាពកម្ចី", "Cancel request":"លុបចោលសំណើ", "Awaiting disbursement":"រង់ចាំបើកប្រាក់",
"Loan issued":"បានបើកប្រាក់កម្ចី", "Download request receipt (PDF)":"ទាញយកបង្កាន់ដៃសំណើ (PDF)",
"View full request details":"មើលព័ត៌មានសំណើទាំងមូល", "View full loan details":"មើលព័ត៌មានកម្ចីទាំងមូល",
"Quick access":"ចូលប្រើរហ័ស", "Next payment":"ការបង់ប្រាក់បន្ទាប់", "Overdue payment":"ការបង់ប្រាក់ហួសកំណត់",
"Statements & receipts":"របាយការណ៍ និងបង្កាន់ដៃ", "Contact support":"ទាក់ទងក្រុមជំនួយ", "Refresh my records":"ផ្ទុកទិន្នន័យឡើងវិញ",
"My requests":"សំណើរបស់ខ្ញុំ", "My issued loans":"កម្ចីដែលបានបើក", "Remaining principal":"ប្រាក់ដើមនៅសល់",
"Amount borrowed":"ប្រាក់កម្ចីដើម", "Total paid":"ប្រាក់បានបង់សរុប", "Overdue amount":"ប្រាក់ហួសកំណត់",
"Latest request":"សំណើចុងក្រោយ", "Loan overview":"សង្ខេបកម្ចី", "Loan cost summary":"សង្ខេបថ្លៃកម្ចី",
"Annual interest rate":"អត្រាការប្រាក់ប្រចាំឆ្នាំ", "Total interest rate":"អត្រាការប្រាក់សរុប",
"Total scheduled interest":"ការប្រាក់សរុបតាមកាលវិភាគ", "Total scheduled repayment":"ប្រាក់សងសរុបតាមកាលវិភាគ",
"Loan progress":"វឌ្ឍនភាពការសងកម្ចី", "Principal repaid":"ប្រាក់ដើមបានសង", "Interest paid":"ការប្រាក់បានបង់",
"Payment history":"ប្រវត្តិបង់ប្រាក់", "Repayment schedule":"កាលវិភាគសងប្រាក់", "Payment calendar":"ប្រតិទិនបង់ប្រាក់",
"Calendar month":"ខែប្រតិទិន", "Today":"ថ្ងៃនេះ", "Payment dates":"កាលបរិច្ឆេទបង់ប្រាក់", "All dates":"គ្រប់កាលបរិច្ឆេទ",
"Choose dates":"ជ្រើសកាលបរិច្ឆេទ", "From":"ចាប់ពី", "To":"ដល់", "Payment receipts":"បង្កាន់ដៃបង់ប្រាក់",
"Choose a payment receipt":"ជ្រើសបង្កាន់ដៃបង់ប្រាក់", "Download receipt (PDF)":"ទាញយកបង្កាន់ដៃ (PDF)",
"Download loan statement (PDF)":"ទាញយករបាយការណ៍កម្ចី (PDF)", "Supporting documents":"ឯកសារគាំទ្រ",
"No documents uploaded yet.":"មិនទាន់មានឯកសារបញ្ចូល។", "Download document":"ទាញយកឯកសារ", "Document type":"ប្រភេទឯកសារ",
"Supporting document":"ឯកសារគាំទ្រ", "Upload document":"បញ្ចូលឯកសារ", "Accepted":"បានទទួលយក", "Needs replacement":"ត្រូវការប្តូរឯកសារ",
"Conversation":"ការសន្ទនា", "Start a new chat":"ចាប់ផ្ដើមការសន្ទនាថ្មី", "General question":"សំណួរទូទៅ",
"Related loan (optional)":"កម្ចីពាក់ព័ន្ធ (មិនបង្ខំ)", "Loan reference":"លេខយោងកម្ចី", "Support team":"ក្រុមជំនួយ",
"Support bot · Automatic reply":"ប្រព័ន្ធជំនួយ · សារឆ្លើយតបស្វ័យប្រវត្តិ", "Type your message…":"សរសេរសាររបស់អ្នក…",
"Type your question…":"សរសេរសំណួររបស់អ្នក…", "Open":"កំពុងបើក", "Resolved":"បានដោះស្រាយ", "Refresh notifications":"ផ្ទុកការជូនដំណឹងឡើងវិញ",
"How to make a payment":"របៀបបង់ប្រាក់", "Report a payment":"រាយការណ៍ការបង់ប្រាក់", "Amount paid ($)":"ចំនួនប្រាក់បានបង់ ($)",
"Date paid":"កាលបរិច្ឆេទបានបង់", "Transfer / receipt reference":"លេខយោងផ្ទេរ / បង្កាន់ដៃ", "Submit for verification":"បញ្ជូនសម្រាប់ផ្ទៀងផ្ទាត់",
"Confirmed":"បានបញ្ជាក់", "Rejected":"បានបដិសេធ", "Pending":"កំពុងរង់ចាំ", "Terms and important dates":"លក្ខខណ្ឌ និងកាលបរិច្ឆេទសំខាន់",
"Repayment term":"រយៈពេលសងប្រាក់", "Disbursed":"បានបើកប្រាក់", "First installment due":"ថ្ងៃបង់ដំបូង", "Final installment due":"ថ្ងៃបង់ចុងក្រោយ",
"Regular installment":"ប្រាក់បង់ប្រចាំខែ", "Final installment":"ប្រាក់បង់ចុងក្រោយ", "Remaining scheduled repayment":"ប្រាក់ត្រូវសងនៅសល់តាមកាលវិភាគ",
"Request reference":"លេខយោងសំណើ", "Requested amount":"ប្រាក់បានស្នើ", "Request date":"កាលបរិច្ឆេទស្នើសុំ", "Decision date":"កាលបរិច្ឆេទសម្រេច",
"Decision notes":"មូលហេតុនៃការសម្រេច", "Customer details":"ព័ត៌មានអតិថិជន", "Back to my requests":"ត្រឡប់ទៅសំណើរបស់ខ្ញុំ",
"Back to my loans":"ត្រឡប់ទៅកម្ចីរបស់ខ្ញុំ", "Payment #":"លើកបង់", "Due date":"ថ្ងៃដល់កំណត់", "Scheduled ($)":"ប្រាក់តាមកាលវិភាគ ($)",
"Paid ($)":"បានបង់ ($)", "Remaining ($)":"នៅសល់ ($)", "Payment date":"កាលបរិច្ឆេទបង់", "Amount ($)":"ចំនួនប្រាក់ ($)",
"Principal ($)":"ប្រាក់ដើម ($)", "Interest ($)":"ការប្រាក់ ($)", "Unapplied ($)":"មិនទាន់បែងចែក ($)",
"Personal":"ផ្ទាល់ខ្លួន", "Housing":"លំនៅឋាន", "SME (individual)":"អាជីវកម្មខ្នាតតូច", "Agriculture":"កសិកម្ម", "Vehicle":"យានយន្ត",
"Change password":"ប្តូរពាក្យសម្ងាត់", "Current password":"ពាក្យសម្ងាត់បច្ចុប្បន្ន", "New password":"ពាក្យសម្ងាត់ថ្មី",
"Repeat new password":"បញ្ចូលពាក្យសម្ងាត់ថ្មីម្ដងទៀត", "Account recovery":"ស្ដារគណនី", "Confirm current password":"បញ្ជាក់ពាក្យសម្ងាត់បច្ចុប្បន្ន",
"Generate recovery code":"បង្កើតលេខកូដស្ដារគណនី", "Multi-factor sign-in":"ចូលគណនីដោយផ្ទៀងផ្ទាត់ច្រើនជំហាន",
"I have already made this payment.":"ខ្ញុំបានបង់ប្រាក់នេះរួចហើយ។",
"I reviewed the estimated cost and understand final terms require staff approval.":"ខ្ញុំបានពិនិត្យការប៉ាន់ប្រមាណ និងយល់ថាលក្ខខណ្ឌចុងក្រោយត្រូវការការអនុម័តពីបុគ្គលិក។",
"Manage your photo, personal details and contact information.":"គ្រប់គ្រងរូបថត ព័ត៌មានផ្ទាល់ខ្លួន និងព័ត៌មានទំនាក់ទំនង។",
"Your loan terms, dates and repayment overview.":"លក្ខខណ្ឌកម្ចី កាលបរិច្ឆេទ និងព័ត៌មានសង្ខេបការសងប្រាក់។",
"Your loan request updates and payment reminders.":"ព័ត៌មានថ្មីអំពីសំណើកម្ចី និងការរំលឹកបង់ប្រាក់។",
"Message our support team about your loan or account.":"ផ្ញើសារទៅក្រុមជំនួយអំពីកម្ចី ឬគណនីរបស់អ្នក។",
"No loans are linked to your account yet.":"មិនទាន់មានកម្ចីភ្ជាប់នឹងគណនីរបស់អ្នក។",
"No payments recorded yet.":"មិនទាន់មានការបង់ប្រាក់បានកត់ត្រា។", "No scheduled payments.":"មិនទាន់មានកាលវិភាគបង់ប្រាក់។",
"Submitted":"បានបញ្ជូន", "months":"ខែ", "due":"ដល់កំណត់", "Installment":"លើកបង់", "Scheduled":"ប្រាក់តាមកាលវិភាគ",
"January":"មករា", "February":"កុម្ភៈ", "March":"មីនា", "April":"មេសា", "May":"ឧសភា", "June":"មិថុនា",
"July":"កក្កដា", "August":"សីហា", "September":"កញ្ញា", "October":"តុលា", "November":"វិច្ឆិកា", "December":"ធ្នូ",
"Mon":"ចន្ទ", "Tue":"អង្គារ", "Wed":"ពុធ", "Thu":"ព្រហស្បតិ៍", "Fri":"សុក្រ", "Sat":"សៅរ៍", "Sun":"អាទិត្យ",
}

KH.update({
"Review your application, supporting documents and decision.":"ពិនិត្យព័ត៌មានសំណើ ឯកសារគាំទ្រ និងការសម្រេច។",
"Not provided":"មិនបានផ្ដល់", "Balances exclude future interest. Payment dates use DD/MM/YYYY; all amounts are USD.":"សមតុល្យមិនរាប់ការប្រាក់អនាគត។ កាលបរិច្ឆេទប្រើ ថ្ងៃ/ខែ/ឆ្នាំ ហើយប្រាក់ទាំងអស់គិតជាដុល្លារអាមេរិក។",
"Green: Paid · Red: Overdue · Blue: Upcoming. Dates shown are installment due dates.":"បៃតង៖ បានបង់ · ក្រហម៖ ហួសកំណត់ · ខៀវ៖ មិនទាន់ដល់កំណត់។ កាលបរិច្ឆេទគឺជាថ្ងៃត្រូវបង់តាមកាលវិភាគ។",
"Your request is submitted only when you confirm below. Final terms require employee approval.":"សំណើត្រូវបានបញ្ជូនតែនៅពេលអ្នកបញ្ជាក់ខាងក្រោម។ លក្ខខណ្ឌចុងក្រោយត្រូវការអនុម័តពីបុគ្គលិក។",
"Thanks for your message! Our support team will reply as soon as possible. Please check this chat for updates.":"អរគុណសម្រាប់សាររបស់អ្នក! ក្រុមជំនួយនឹងឆ្លើយតបឱ្យបានឆាប់តាមដែលអាចធ្វើបាន។ សូមពិនិត្យការសន្ទនានេះដើម្បីមើលព័ត៌មានថ្មី។",
"No requests match these filters. Clear the search or choose All statuses.":"មិនមានសំណើត្រូវនឹងការស្វែងរក។ សូមលុបការស្វែងរក ឬជ្រើសស្ថានភាពទាំងអស់។",
"You have not submitted a request yet.":"អ្នកមិនទាន់បានបញ្ជូនសំណើ។",
"Submitted → Pending review → Approved or Declined. Approved requests are then issued by the loan team.":"បានបញ្ជូន → រង់ចាំពិនិត្យ → បានអនុម័ត ឬបដិសេធ។ ក្រុមកម្ចីនឹងរៀបចំបើកប្រាក់បន្ទាប់ពីអនុម័ត។",
"Interest is fixed at the stated percentage of the original amount for the entire loan term. ":"ការប្រាក់ត្រូវគណនាថេរតាមអត្រាលើប្រាក់ដើមសម្រាប់រយៈពេលកម្ចីទាំងមូល។ ",
"Interest is calculated monthly on the remaining principal (annual rate ÷ 12). ":"ការប្រាក់គណនាប្រចាំខែលើប្រាក់ដើមនៅសល់ (អត្រាប្រចាំឆ្នាំ ÷ 12)។ ",
"Totals exclude additional fees or penalties.":"ចំនួនសរុបមិនរាប់ថ្លៃបន្ថែម ឬប្រាក់ពិន័យ។",
"Interest":"ការប្រាក់", "Principal":"ប្រាក់ដើម", "Remaining":"នៅសល់", "Paid installments":"ចំនួនលើកបានបង់", "Upcoming installments":"ចំនួនលើកមិនទាន់ដល់កំណត់", "Overdue installments":"ចំនួនលើកហួសកំណត់",
"Your password and sign-in security.":"ពាក្យសម្ងាត់ និងសុវត្ថិភាពចូលគណនីរបស់អ្នក។",
"Remaining principal excludes future interest and is not a settlement quote.":"ប្រាក់ដើមនៅសល់មិនរាប់ការប្រាក់អនាគត ហើយមិនមែនជាសម្រង់សម្រាប់បង់ផ្ដាច់។",
"Remaining principal excludes future interest; it is not a settlement quote.":"ប្រាក់ដើមនៅសល់មិនរាប់ការប្រាក់អនាគត ហើយមិនមែនជាសម្រង់សម្រាប់បង់ផ្ដាច់។",
"Refresh conversations":"ផ្ទុកការសន្ទនាឡើងវិញ", "Back to conversations":"ត្រឡប់ទៅការសន្ទនា",
})

KH.update({
"View":"មើល", "Enter your request details first.":"សូមបញ្ចូលព័ត៌មានសំណើជាមុន។", "Credit Desk · Customer":"Credit Desk · អតិថិជន",
"Click the circular profile button beside Credit Desk to save your name, contact details and location before applying.":"សូមចុចរូបប្រវត្តិរូបនៅជិត Credit Desk ដើម្បីរក្សាទុកឈ្មោះ ព័ត៌មានទំនាក់ទំនង និងទីតាំង មុនស្នើសុំកម្ចី។",
"Receipt reference, date or amount":"លេខយោងបង្កាន់ដៃ កាលបរិច្ឆេទ ឬចំនួនប្រាក់",
"No payments match these filters. Clear the search or widen the date range.":"មិនមានការបង់ប្រាក់ត្រូវនឹងការស្វែងរក។ សូមលុបការស្វែងរក ឬពង្រីកចន្លោះកាលបរិច្ឆេទ។",
"You're all caught up. Your loan updates and payment reminders will appear here.":"អ្នកបានមើលព័ត៌មានថ្មីទាំងអស់។ ព័ត៌មានកម្ចី និងការរំលឹកបង់ប្រាក់នឹងបង្ហាញនៅទីនេះ។",
"Open Customer support from the sidebar.":"បើកជំនួយអតិថិជនពីម៉ឺនុយចំហៀង។",
"The request date is recorded automatically. An employee reviews every request.":"កាលបរិច្ឆេទស្នើសុំកត់ត្រាដោយស្វ័យប្រវត្តិ។ បុគ្គលិកពិនិត្យរាល់សំណើ។",
"Reference, purpose or product":"លេខយោង គោលបំណង ឬប្រភេទកម្ចី",
"No loans are linked to your account yet. An employee links existing records or issues an approved loan.":"មិនទាន់មានកម្ចីភ្ជាប់គណនីអ្នក។ បុគ្គលិកអាចភ្ជាប់កំណត់ត្រាចាស់ ឬបើកកម្ចីដែលបានអនុម័ត។",
"Payments include interest. Principal remaining excludes future interest; it is not a settlement quote.":"ប្រាក់បង់រួមទាំងការប្រាក់។ ប្រាក់ដើមនៅសល់មិនរាប់ការប្រាក់អនាគត និងមិនមែនជាចំនួនសម្រាប់បង់ផ្ដាច់។",
"Paid: fully covered. Upcoming: payment remains and the due date has not passed. Overdue: payment remains after its due date.":"បានបង់៖ បង់គ្រប់ចំនួន។ មិនទាន់ដល់កំណត់៖ នៅសល់ប្រាក់ត្រូវបង់មុនថ្ងៃកំណត់។ ហួសកំណត់៖ នៅសល់ប្រាក់ក្រោយថ្ងៃកំណត់។",
"Principal repays the amount borrowed. Interest is the cost of the loan. Payments cover each installment's interest first, then its principal.":"ប្រាក់ដើមជាប្រាក់ដែលអ្នកខ្ចី។ ការប្រាក់ជាថ្លៃកម្ចី។ ការបង់នីមួយៗគ្របការប្រាក់ជាមុន រួចទើបកាត់ប្រាក់ដើម។",
"The From date must be on or before the To date.":"ថ្ងៃចាប់ផ្ដើមត្រូវមុន ឬស្មើថ្ងៃបញ្ចប់។", "Loan reference or product":"លេខយោង ឬប្រភេទកម្ចី",
"No loans match these filters. Clear the search or choose All statuses.":"មិនមានកម្ចីត្រូវនឹងការស្វែងរក។ សូមលុបការស្វែងរក ឬជ្រើសស្ថានភាពទាំងអស់។",
"Province or city, district and address.":"ខេត្ត ឬក្រុង ស្រុក/ខណ្ឌ និងអាសយដ្ឋាន។",
"You can cancel this request until the loan team reviews it.":"អ្នកអាចលុបចោលសំណើមុនក្រុមកម្ចីពិនិត្យ។",
"Declined · Review the decision notes below.":"បានបដិសេធ · សូមមើលមូលហេតុខាងក្រោម។", "Click to view photo":"ចុចដើម្បីមើលរូបថត",
"Cancelled · This request will not be reviewed.":"បានលុបចោល · សំណើនេះនឹងមិនត្រូវបានពិនិត្យ។",
"Pending review · Your request is waiting for the loan team.":"កំពុងរង់ចាំពិនិត្យ · សំណើរបស់អ្នកកំពុងរង់ចាំក្រុមកម្ចី។",
"PDF, JPG or PNG · maximum 10 MB. Only you and the loan team can access these files.":"PDF, JPG ឬ PNG · អតិបរមា 10 MB។ មានតែអ្នក និងក្រុមកម្ចីអាចបើកឯកសារទាំងនេះ។",
"Choose a supporting document before pressing Upload document.":"សូមជ្រើសឯកសារមុនចុចបញ្ចូលឯកសារ។",
"Replies appear automatically while the chat is open. The support team will reply when available. Chats are deleted after 24 hours without a new message.":"សារឆ្លើយតបបង្ហាញដោយស្វ័យប្រវត្តិពេលបើកការសន្ទនា។ ក្រុមជំនួយនឹងឆ្លើយពេលអាចធ្វើបាន។ ការសន្ទនាលុបក្រោយគ្មានសារថ្មី 24 ម៉ោង។",
"Chats are deleted after 24 hours without a new message.":"ការសន្ទនាលុបក្រោយគ្មានសារថ្មី 24 ម៉ោង។",
"This chat has expired. Start a new chat to contact support.":"ការសន្ទនានេះផុតកំណត់ហើយ។ សូមចាប់ផ្ដើមការសន្ទនាថ្មីដើម្បីទាក់ទងជំនួយ។",
"This conversation is resolved. Sending another reply reopens it.":"ការសន្ទនាបានដោះស្រាយ។ ការផ្ញើសារថ្មីនឹងបើកវាឡើងវិញ។",
"Include your loan reference with your payment. Report an actual payment below; your balance changes only after staff verify receipt. This website does not transfer money.":"សូមបញ្ចូលលេខយោងកម្ចីពេលបង់ប្រាក់។ រាយការណ៍ការបង់ប្រាក់ពិតខាងក្រោម។ សមតុល្យផ្លាស់ប្ដូរតែក្រោយបុគ្គលិកផ្ទៀងផ្ទាត់ថាបានទទួលប្រាក់។ គេហទំព័រនេះមិនផ្ទេរប្រាក់ឡើយ។",
"Contact the support team for the verified payment destination before transferring money.":"សូមទាក់ទងក្រុមជំនួយដើម្បីបញ្ជាក់ទីតាំងបង់ប្រាក់ មុនផ្ទេរប្រាក់។",
"Payment reported. Staff must verify it before it appears in your payment history.":"បានរាយការណ៍ការបង់ប្រាក់។ បុគ្គលិកត្រូវផ្ទៀងផ្ទាត់មុនបង្ហាញក្នុងប្រវត្តិបង់ប្រាក់។",
"Generate a private, single-use recovery code for Forgot password. A new code replaces the previous one.":"បង្កើតលេខកូដសម្ងាត់ប្រើបានម្ដង ដើម្បីស្ដារពាក្យសម្ងាត់។ កូដថ្មីជំនួសកូដចាស់។",
"Account":"គណនី", "Enabled. You will be asked for a 6-digit code at every sign-in. To remove it, ask an Administrator.":"បានបើក។ អ្នកត្រូវបញ្ចូលកូដ 6 ខ្ទង់រាល់ពេលចូល។ សូមទាក់ទងអ្នកគ្រប់គ្រងដើម្បីបិទ។",
"Save this code privately now. It will not be shown again.":"សូមរក្សាកូដនេះជាសម្ងាត់ឥឡូវនេះ។ វានឹងមិនបង្ហាញម្ដងទៀត។",
"Current password is incorrect.":"ពាក្យសម្ងាត់បច្ចុប្បន្នមិនត្រឹមត្រូវ។", "The two new passwords do not match.":"ពាក្យសម្ងាត់ថ្មីទាំងពីរមិនដូចគ្នា។", "Password changed.":"បានប្ដូរពាក្យសម្ងាត់។",
"Pending review":"កំពុងរង់ចាំពិនិត្យ", "Welcome":"ស្វាគមន៍", "Manage your requests and view your loans.":"គ្រប់គ្រងសំណើ និងមើលកម្ចីរបស់អ្នក។",
"Payment reminder":"ការរំលឹកបង់ប្រាក់", "Installments paid":"ចំនួនលើកបានបង់", "installments paid":"លើកបានបង់", "installments remaining":"លើកនៅសល់",
"complete":"បានបំពេញ", "Final payment":"ប្រាក់បង់ចុងក្រោយ", "total interest over the loan term":"ការប្រាក់សរុបសម្រាប់រយៈពេលកម្ចី",
"annual interest":"ការប្រាក់ប្រចាំឆ្នាំ", "Loan request received":"បានទទួលសំណើកម្ចី", "Loan request declined":"សំណើកម្ចីបានបដិសេធ",
"Loan request approved":"សំណើកម្ចីបានអនុម័ត", "Loan request cancelled":"សំណើកម្ចីបានលុបចោល", "Loan record available":"មានកំណត់ត្រាកម្ចី",
"Payment overdue":"ការបង់ប្រាក់ហួសកំណត់", "Payment due today":"ប្រាក់ត្រូវបង់ថ្ងៃនេះ", "Payment due tomorrow":"ប្រាក់ត្រូវបង់ថ្ងៃស្អែក",
"Upcoming payment reminder":"ការរំលឹកបង់ប្រាក់ជិតដល់កំណត់", "Support replied":"ក្រុមជំនួយបានឆ្លើយតប",
})

KH.update({"Scheduled payment":"ប្រាក់ត្រូវបង់តាមកាលវិភាគ", "Amount paid":"ប្រាក់បានបង់", "Amount overdue":"ប្រាក់ហួសកំណត់", "Amount remaining":"ប្រាក់នៅសល់"})

KH.update({
"Help / FAQ":"ជំនួយ / សំណួរញឹកញាប់", "Before you apply":"មុនស្នើសុំកម្ចី", "Required information":"ព័ត៌មានចាំបាច់",
"Complete my profile":"បំពេញប្រវត្តិរូបខ្ញុំ", "Start a loan request":"ចាប់ផ្ដើមសំណើកម្ចី", "Download repayment schedule (PDF)":"ទាញយកកាលវិភាគសងប្រាក់ (PDF)",
"PDF downloads require reportlab.":"ការទាញយក PDF ត្រូវការកម្មវិធី reportlab។",
"No loan requests yet":"មិនទាន់មានសំណើកម្ចី", "No loans to display":"មិនទាន់មានកម្ចីបង្ហាញ", "No payments recorded yet":"មិនទាន់មានការបង់ប្រាក់បានកត់ត្រា", "You are all caught up":"អ្នកបានមើលព័ត៌មានថ្មីទាំងអស់",
"Start by saving your profile, then review the cost estimate and submit a loan request. You can track its decision here.":"សូមរក្សាទុកប្រវត្តិរូបជាមុន រួចពិនិត្យការប៉ាន់ប្រមាណថ្លៃកម្ចី និងបញ្ជូនសំណើ។ អ្នកអាចតាមដានការសម្រេចនៅទីនេះ។",
"An approved request appears here after the loan team issues it. If you already have a loan, ask support to check that it is linked to your account.":"សំណើបានអនុម័តនឹងបង្ហាញនៅទីនេះបន្ទាប់ពីក្រុមកម្ចីបើកប្រាក់។ បើអ្នកមានកម្ចីស្រាប់ សូមស្នើក្រុមជំនួយពិនិត្យការភ្ជាប់នឹងគណនី។",
"Your confirmed payments and downloadable receipts will appear here. Check the repayment calendar for due dates. Report an actual payment using Report a payment.":"ការបង់ប្រាក់បានបញ្ជាក់ និងបង្កាន់ដៃនឹងបង្ហាញនៅទីនេះ។ មើលប្រតិទិនដើម្បីដឹងថ្ងៃកំណត់ ហើយប្រើ រាយការណ៍ការបង់ប្រាក់ ក្រោយបានបង់ប្រាក់ពិត។",
"Loan decisions, next-payment reminders and support replies will appear here when available.":"ការសម្រេចសំណើ ការរំលឹកបង់ប្រាក់បន្ទាប់ និងសារឆ្លើយតបពីក្រុមជំនួយនឹងបង្ហាញនៅទីនេះ។",
"Email and a profile photo are optional. Save your profile before submitting a request.":"អ៊ីមែល និងរូបថតមិនបង្ខំ។ សូមរក្សាទុកប្រវត្តិរូបមុនបញ្ជូនសំណើ។",
"Choose the amount, term and loan product, explain the purpose, and review the estimate before confirming.":"ជ្រើសចំនួនប្រាក់ រយៈពេល និងប្រភេទកម្ចី ពន្យល់គោលបំណង និងពិនិត្យការប៉ាន់ប្រមាណមុនបញ្ជាក់។",
"The loan team may request identity, income or bank documents, depending on the application. They are not automatically required to submit this form.":"ក្រុមកម្ចីអាចស្នើឯកសារអត្តសញ្ញាណ ប្រាក់ចំណូល ឬធនាគារ តាមប្រភេទសំណើ។ ឯកសារទាំងនេះមិនមែនជាលក្ខខណ្ឌបង្ខំសម្រាប់បញ្ជូនទម្រង់នេះទេ។",
"After submitting, open Request details to upload PDF, JPG or PNG documents up to 10 MB each while the request is pending review.":"ក្រោយបញ្ជូន សូមបើក ព័ត៌មានលម្អិតសំណើ ដើម្បីបញ្ចូលឯកសារ PDF, JPG ឬ PNG មួយឯកសារមិនលើស 10 MB ខណៈរង់ចាំពិនិត្យ។",
"Understand your loan, payments and application process.":"ស្វែងយល់អំពីកម្ចី ការបង់ប្រាក់ និងដំណើរការស្នើសុំ។",
"How do I request a loan?":"តើខ្ញុំស្នើសុំកម្ចីដោយរបៀបណា?",
"Complete your profile, choose the amount and term, enter a product and purpose, then preview and confirm. Submitting a request does not guarantee approval.":"បំពេញប្រវត្តិរូប ជ្រើសចំនួនប្រាក់ និងរយៈពេល បញ្ចូលប្រភេទកម្ចី និងគោលបំណង រួចពិនិត្យ និងបញ្ជាក់។ ការបញ្ជូនសំណើមិនធានាការអនុម័តឡើយ។",
"What do the request statuses mean?":"តើស្ថានភាពសំណើមានន័យដូចម្តេច?",
"Pending review means the loan team has not decided yet. Approved means accepted, but the loan may still await disbursement. Declined means not accepted; read the decision notes. Cancelled means you withdrew the request.":"រង់ចាំពិនិត្យ៖ ក្រុមកម្ចីមិនទាន់សម្រេច។ បានអនុម័ត៖ ទទួលយក ប៉ុន្តែអាចរង់ចាំបើកប្រាក់។ បានបដិសេធ៖ មិនទទួលយក សូមអានមូលហេតុ។ បានលុបចោល៖ អ្នកបានដកសំណើ។",
"How is interest calculated?":"តើការប្រាក់គណនាយ៉ាងដូចម្តេច?",
"Check the interest method on Loan details. Flat total interest is calculated once on the original principal for the full term. Annual reducing-balance interest is calculated monthly on the remaining principal. The application estimate is not your final approved rate.":"មើលវិធីគណនាក្នុងព័ត៌មានលម្អិតកម្ចី។ ការប្រាក់ថេរសរុបគណនាលើប្រាក់ដើមសម្រាប់រយៈពេលទាំងមូល។ ការប្រាក់ប្រចាំឆ្នាំលើប្រាក់ដើមថយចុះគណនាប្រចាំខែលើប្រាក់ដើមនៅសល់។ ការប៉ាន់ប្រមាណមិនមែនជាអត្រាអនុម័តចុងក្រោយ។",
"Why is the final payment different?":"ហេតុអ្វីប្រាក់បង់ចុងក្រោយខុសគេ?",
"Payments are rounded to cents. The final installment is adjusted so the total principal and scheduled interest reconcile exactly.":"ប្រាក់បង់ត្រូវបង្គត់ដល់សេន។ ប្រាក់បង់ចុងក្រោយត្រូវកែតម្រូវដើម្បីឱ្យប្រាក់ដើម និងការប្រាក់សរុបត្រឹមត្រូវ។",
"What do Paid, Upcoming and Overdue mean?":"តើ បានបង់ មិនទាន់ដល់កំណត់ និងហួសកំណត់ មានន័យអ្វី?",
"Paid means the installment is fully covered. Upcoming means an amount remains and its due date has not passed. Overdue means an amount remains after the due date. A partial payment leaves a remaining amount.":"បានបង់៖ បង់គ្រប់ចំនួន។ មិនទាន់ដល់កំណត់៖ នៅសល់ប្រាក់មុនថ្ងៃកំណត់។ ហួសកំណត់៖ នៅសល់ប្រាក់ក្រោយថ្ងៃកំណត់។ បង់តែផ្នែកខ្លះនៅតែមានប្រាក់នៅសល់។",
"Does remaining principal include interest?":"តើប្រាក់ដើមនៅសល់រួមការប្រាក់ដែរឬទេ?",
"No. Remaining principal is the borrowed amount still unpaid. Remaining scheduled repayment includes the unpaid interest in the schedule. Neither is a payoff quote.":"ទេ។ ប្រាក់ដើមនៅសល់គឺប្រាក់ខ្ចីមិនទាន់សង។ ប្រាក់សងនៅសល់តាមកាលវិភាគរួមការប្រាក់មិនទាន់បង់។ ចំនួនទាំងនេះមិនមែនជាសម្រង់បង់ផ្ដាច់ទេ។",
"How do I record a payment?":"តើខ្ញុំរាយការណ៍ការបង់ប្រាក់ដោយរបៀបណា?",
"Follow the verified payment instructions or contact support first. After paying, report the date, amount and transfer reference. Staff must confirm receipt before your balance changes. The website does not transfer money.":"សូមធ្វើតាមការណែនាំបានផ្ទៀងផ្ទាត់ ឬទាក់ទងជំនួយជាមុន។ ក្រោយបង់ប្រាក់ រាយការណ៍ថ្ងៃ ចំនួន និងលេខយោងផ្ទេរ។ បុគ្គលិកត្រូវបញ្ជាក់ថាបានទទួលប្រាក់ មុនសមតុល្យផ្លាស់ប្ដូរ។ គេហទំព័រមិនផ្ទេរប្រាក់ឡើយ។",
"Where can I download my records?":"តើខ្ញុំអាចទាញយកកំណត់ត្រានៅឯណា?",
"Request receipts are in request history and Request details. Payment receipts are under My loans & payments. Loan details includes statement and repayment schedule downloads. PDF exports are in English.":"បង្កាន់ដៃសំណើនៅក្នុងប្រវត្តិសំណើ និងព័ត៌មានលម្អិតសំណើ។ បង្កាន់ដៃបង់ប្រាក់នៅក្នុងកម្ចី និងការបង់ប្រាក់។ ព័ត៌មានលម្អិតកម្ចីមានរបាយការណ៍ និងកាលវិភាគសងប្រាក់សម្រាប់ទាញយក។ PDF ជាភាសាអង់គ្លេស។",
"Can I cancel or edit a submitted request?":"តើខ្ញុំអាចលុបចោល ឬកែសំណើបានបញ្ជូនឬទេ?",
"You can cancel a pending request before staff review it. To change its amount, term or purpose, cancel it and submit a new request. Contact support about a request already reviewed.":"អ្នកអាចលុបចោលសំណើមុនបុគ្គលិកពិនិត្យ។ ដើម្បីប្ដូរចំនួនប្រាក់ រយៈពេល ឬគោលបំណង សូមលុបចោលហើយបញ្ជូនសំណើថ្មី។ សូមទាក់ទងជំនួយសម្រាប់សំណើដែលបានពិនិត្យរួច។",
"How long are support chats kept?":"តើការសន្ទនាជំនួយរក្សាទុកយូរប៉ុន្មាន?",
"Chats expire 24 hours after the last message. A new message restarts that timer. Expired conversations are deleted when support data refreshes. Keep important confirmations outside the chat.":"ការសន្ទនាផុតកំណត់ក្រោយសារចុងក្រោយ 24 ម៉ោង។ សារថ្មីចាប់ពេលវេលាឡើងវិញ។ ការសន្ទនាផុតកំណត់លុបពេលផ្ទុកទិន្នន័យជំនួយឡើងវិញ។ សូមរក្សាការបញ្ជាក់សំខាន់នៅក្រៅការសន្ទនា។",
"What if I forget my password?":"បើខ្ញុំភ្លេចពាក្យសម្ងាត់ ត្រូវធ្វើអ្វី?",
"Use Forgot password on the sign-in screen with your saved recovery code. Codes are single-use. Generate a replacement in My account. If you have no code, ask an administrator for help.":"ប្រើមុខងារភ្លេចពាក្យសម្ងាត់នៅទំព័រចូល ជាមួយកូដស្ដារដែលបានរក្សាទុក។ កូដប្រើបានតែម្ដង។ បង្កើតកូដថ្មីនៅគណនីខ្ញុំ។ បើគ្មានកូដ សូមស្នើជំនួយពីអ្នកគ្រប់គ្រង។",
})

KH.update({
"Payment status":"ស្ថានភាពការបង់ប្រាក់", "Search installments":"ស្វែងរកលើកបង់ប្រាក់", "Date, installment number or amount":"កាលបរិច្ឆេទ លេខលើកបង់ ឬចំនួនប្រាក់",
"Matching installments":"ចំនួនលើកបង់ត្រូវនឹងការស្វែងរក", "No installments match. Choose All statuses or clear the search.":"មិនមានលើកបង់ត្រូវនឹងការស្វែងរក។ សូមជ្រើសស្ថានភាពទាំងអស់ ឬលុបការស្វែងរក។",
"Profile completion":"ការបំពេញប្រវត្តិរូប", "Still needed":"ព័ត៌មាននៅខ្វះ", "All required profile details are complete.":"ព័ត៌មានប្រវត្តិរូបចាំបាច់បានបំពេញគ្រប់។",
"Email and a profile photo are optional and do not affect completion.":"អ៊ីមែល និងរូបថតមិនបង្ខំ ហើយមិនប៉ះពាល់ដល់ភាគរយបំពេញ។",
"Dismiss confirmation":"បិទសារបញ្ជាក់", "Profile saved":"បានរក្សាទុកប្រវត្តិរូប", "Your name, contact details and selected photo have been saved.":"ឈ្មោះ ព័ត៌មានទំនាក់ទំនង និងរូបថតដែលបានជ្រើស ត្រូវបានរក្សាទុក។",
"Loan request submitted":"បានបញ្ជូនសំណើកម្ចី", "Your request is saved and awaiting review. Download its receipt from My request history.":"សំណើត្រូវបានរក្សាទុក និងរង់ចាំពិនិត្យ។ ទាញយកបង្កាន់ដៃពីប្រវត្តិសំណើរបស់ខ្ញុំ។",
"Request updated":"បានធ្វើបច្ចុប្បន្នភាពសំណើ", "Document uploaded":"បានបញ្ចូលឯកសារ", "Your document is saved and available to the loan team.":"ឯកសារត្រូវបានរក្សាទុក ហើយក្រុមកម្ចីអាចពិនិត្យបាន។",
})

KH.update({"Interest rate (%)":"អត្រាការប្រាក់ (%)", "Total interest":"ការប្រាក់សរុប", "Total flat interest for the entire loan term. This is an estimate; staff approve the final rate.":"ការប្រាក់ថេរសរុបសម្រាប់រយៈពេលកម្ចីទាំងមូល។ នេះជាការប៉ាន់ប្រមាណ ហើយបុគ្គលិកអនុម័តអត្រាចុងក្រោយ។"})

KH.update({
"Estimated and approved terms":"លក្ខខណ្ឌប៉ាន់ប្រមាណ និងលក្ខខណ្ឌបានអនុម័ត", "Estimate reviewed by customer":"ការប៉ាន់ប្រមាណដែលអតិថិជនបានពិនិត្យ",
"Approved terms":"លក្ខខណ្ឌបានអនុម័ត", "No estimate was saved with this older request.":"សំណើចាស់នេះមិនមានការប៉ាន់ប្រមាណបានរក្សាទុក។",
"No approved offer yet.":"មិនទាន់មានលក្ខខណ្ឌបានអនុម័ត។", "No approved offer for this request.":"មិនមានលក្ខខណ្ឌបានអនុម័តសម្រាប់សំណើនេះ។",
"Total flat interest":"ការប្រាក់ថេរសរុប", "Annual reducing-balance interest":"ការប្រាក់ប្រចាំឆ្នាំលើប្រាក់ដើមថយចុះ",
"Payment dates are assigned when the loan is issued.":"កាលបរិច្ឆេទបង់ប្រាក់កំណត់ពេលបើកប្រាក់កម្ចី។",
"Approved terms differ from the estimate. Check the rate, calculation method, term and payments carefully.":"លក្ខខណ្ឌបានអនុម័តខុសពីការប៉ាន់ប្រមាណ។ សូមពិនិត្យអត្រា វិធីគណនា រយៈពេល និងប្រាក់បង់ឱ្យបានច្បាស់។",
"Approved terms match the saved estimate.":"លក្ខខណ្ឌបានអនុម័តត្រូវនឹងការប៉ាន់ប្រមាណបានរក្សាទុក។",
"Your unfinished application has been restored.":"បានស្ដារសំណើដែលមិនទាន់បញ្ចប់របស់អ្នក។", "Draft could not be saved. Keep this page open and try Save draft again.":"មិនអាចរក្សាទុកសេចក្ដីព្រាង។ សូមបន្តបើកទំព័រ ហើយសាកល្បងរក្សាទុកម្ដងទៀត។",
"Save draft":"រក្សាទុកសេចក្ដីព្រាង", "Discard draft":"លុបសេចក្ដីព្រាង", "Draft saved":"បានរក្សាទុកសេចក្ដីព្រាង", "Draft discarded":"បានលុបសេចក្ដីព្រាង",
"Your unfinished application is saved to your account.":"សំណើមិនទាន់បញ្ចប់ត្រូវបានរក្សាទុកក្នុងគណនីរបស់អ្នក។",
"Changes save automatically after you finish editing a field. A draft is not a submitted request.":"ការកែប្រែរក្សាទុកស្វ័យប្រវត្តិក្រោយអ្នកបញ្ចប់កែប្រអប់ព័ត៌មាន។ សេចក្ដីព្រាងមិនមែនជាសំណើបានបញ្ជូនទេ។",
})

KH.update({"Complete your profile to apply.":"សូមបំពេញប្រវត្តិរូបដើម្បីស្នើសុំ។", "I understand this is an estimate.":"ខ្ញុំយល់ថានេះជាការប៉ាន់ប្រមាណ។", "payments":"ការបង់ប្រាក់"})

KH.update({"Recent conversations":"ការសន្ទនាថ្មីៗ", "New chat":"ការសន្ទនាថ្មី", "No conversations yet.":"មិនទាន់មានការសន្ទនា។", "unread":"មិនទាន់អាន", "You":"អ្នក", "Automatic reply":"សារឆ្លើយតបស្វ័យប្រវត្តិ", "Chat expires in":"ការសន្ទនាផុតកំណត់ក្នុង", "How can we help?":"តើអ្នកត្រូវការជំនួយអ្វី?", "Send a message to our support team.":"ផ្ញើសារទៅក្រុមជំនួយរបស់យើង។"})

KH.update({"Messages":"សារ", "New message":"សារថ្មី", "Back to inbox":"ត្រឡប់ទៅប្រអប់សារ", "Unread messages":"សារមិនទាន់អាន", "Show":"បង្ហាញ", "All messages":"សារទាំងអស់", "Unread":"មិនទាន់អាន", "Payment notices":"ការជូនដំណឹងបង់ប្រាក់", "No overdue payments.":"មិនមានប្រាក់ហួសកំណត់។", "System payment notice":"ការជូនដំណឹងបង់ប្រាក់ពីប្រព័ន្ធ", "days overdue":"ថ្ងៃហួសកំណត់", "Discuss this payment":"ពិភាក្សាអំពីការបង់ប្រាក់នេះ", "No messages here yet.":"មិនទាន់មានសារនៅទីនេះ។", "Awaiting support reply":"កំពុងរង់ចាំការឆ្លើយតបពីក្រុមជំនួយ", "Open conversation":"បើកការសន្ទនា", "Open messages":"បើកសារ", "Sent":"បានផ្ញើ", "Seen":"បានមើល"})

KH.update({"Undo":"ត្រឡប់វិញ", "Nothing to undo yet.":"មិនទាន់មានសកម្មភាពត្រូវត្រឡប់វិញ។", "Action undone":"បានត្រឡប់សកម្មភាពវិញ", "Profile edit":"ការកែប្រវត្តិរូប", "Application draft":"សេចក្ដីព្រាងសំណើ", "Discarded draft":"សេចក្ដីព្រាងបានលុប", "Submitted request":"សំណើបានបញ្ជូន", "Cancelled request":"សំណើបានលុបចោល", "Sent message":"សារបានផ្ញើ", "Uploaded document":"ឯកសារបានបញ្ចូល", "Message withdrawn":"សារត្រូវបានដកវិញ", "Support conversation":"ការសន្ទនាជំនួយ", "This action can no longer be undone because its record changed.":"មិនអាចត្រឡប់សកម្មភាពនេះវិញ ព្រោះកំណត់ត្រាបានផ្លាស់ប្ដូរ។", "Undo could not be saved. Please try again.":"មិនអាចរក្សាទុកការត្រឡប់វិញ។ សូមសាកល្បងម្ដងទៀត។"})

KH.update({"Resume application":"បន្តបំពេញសំណើ"})


def mobile_styles():
    st.markdown("""<style>
      .cd-phone-cards {display:none;}
      html,body,[data-testid="stApp"] {font-family:"Noto Sans Khmer","Khmer OS System","Leelawadee UI",sans-serif;}
      [data-testid="stMain"] p,[data-testid="stMain"] label {line-height:1.7;}
      @media(max-width:640px){
        [data-testid="stMainBlockContainer"] {padding:5rem 1rem 5.5rem!important;max-width:100%!important;}
        [data-testid="stMain"] h1 {font-size:1.8rem!important;line-height:1.5!important;}
        [data-testid="stMain"] h2 {font-size:1.35rem!important;line-height:1.6!important;}
        [data-testid="stMain"] input,[data-testid="stMain"] textarea {font-size:16px!important;}
        [data-testid="stMain"] button {min-height:46px!important;white-space:normal!important;}
        [data-testid="stMain"] [data-testid="stHorizontalBlock"] {flex-wrap:wrap!important;gap:.75rem!important;}
        [data-testid="stMain"] [data-testid="stColumn"] {width:100%!important;flex:1 1 100%!important;min-width:0!important;}
        [data-testid="stMain"] [data-testid="stMetricValue"] {font-size:1.7rem!important;}
        [data-testid="stMain"] [data-testid="stMetricLabel"] {white-space:normal!important;}
        [data-testid="stMain"] [data-testid="stDataFrame"] {display:none!important;}
        .cd-phone-cards {display:grid;gap:12px;margin:12px 0;}
        .cd-phone-card {background:#FFF;border:1px solid #CBD5E1;border-radius:12px;padding:14px;}
        .cd-phone-card>div {display:flex;justify-content:space-between;gap:14px;padding:5px 0;}
        .cd-phone-card span {color:#64748B;} .cd-phone-card strong {text-align:right;overflow-wrap:anywhere;}
        [role="dialog"] {width:calc(100vw - 16px)!important;max-width:100%!important;max-height:92dvh!important;overflow:auto!important;}
        [data-testid="stChatMessage"] {padding:.75rem!important;gap:.5rem!important;}
        [data-testid="stChatMessage"] p {overflow-wrap:anywhere;}
        [data-testid="stChatInput"] textarea {font-size:16px!important;min-height:44px!important;}
        .st-key-customer_notification_bell {right:14px!important;top:12px!important;}
        #cd-sidebar-toggle {top:12px!important;left:12px!important;min-height:44px!important;}
      }
    </style>""",unsafe_allow_html=True)


# My account - email and Google sign-in (v25)
KH.update({
"Your email, sign-in methods and security.":"អ៊ីមែល វិធីចូលគណនី និងសុវត្ថិភាពរបស់អ្នក។",
"Verified":"បានផ្ទៀងផ្ទាត់", "Not verified":"មិនទាន់ផ្ទៀងផ្ទាត់", "No email address yet":"មិនទាន់មានអ៊ីមែល",
"Sign-in methods":"វិធីចូលគណនី", "Email address":"អាសយដ្ឋានអ៊ីមែល",
"Used to sign in with Google and to receive password reset codes.":"ប្រើសម្រាប់ចូលដោយ Google និងទទួលលេខកូដកំណត់ពាក្យសម្ងាត់ឡើងវិញ។",
"New email address":"អ៊ីមែលថ្មី", "Confirm current password":"បញ្ជាក់ពាក្យសម្ងាត់បច្ចុប្បន្ន",
"Save email":"រក្សាទុកអ៊ីមែល", "Email saved. Verify it below.":"បានរក្សាទុកអ៊ីមែល។ សូមផ្ទៀងផ្ទាត់វានៅខាងក្រោម។",
"Your email is verified.":"អ៊ីមែលរបស់អ្នកបានផ្ទៀងផ្ទាត់ហើយ។", "Google sign-in is linked.":"បានភ្ជាប់ការចូលដោយ Google។",
"Verify your email":"ផ្ទៀងផ្ទាត់អ៊ីមែលរបស់អ្នក", "choose one way":"ជ្រើសវិធីមួយ",
"Sign in with the Google account of this address. It also links Google to this account.":"ចូលដោយគណនី Google នៃអ៊ីមែលនេះ។ វាក៏ភ្ជាប់ Google ទៅគណនីនេះផងដែរ។",
"Verify with Google":"ផ្ទៀងផ្ទាត់ដោយ Google", "We email you a 6-digit code.":"យើងផ្ញើលេខកូដ 6 ខ្ទង់ទៅអ៊ីមែលរបស់អ្នក។",
"Email me a code":"ផ្ញើលេខកូដមកអ៊ីមែលខ្ញុំ", "Code sent to":"បានផ្ញើលេខកូដទៅ", "6-digit code":"លេខកូដ 6 ខ្ទង់",
"Verify email":"ផ្ទៀងផ្ទាត់អ៊ីមែល",
"Email verification is not switched on for this installation. An Administrator can confirm your address in User management.":"ការផ្ទៀងផ្ទាត់អ៊ីមែលមិនទាន់បើកទេ។ អ្នកគ្រប់គ្រងអាចបញ្ជាក់អ៊ីមែលរបស់អ្នកនៅក្នុងទំព័រ User management។",
"You sign in with Google, so a password is optional.":"អ្នកចូលដោយ Google ដូច្នេះពាក្យសម្ងាត់មិនចាំបាច់ទេ។",
"Set a password":"កំណត់ពាក្យសម្ងាត់",
"Password set. You can now also sign in with your username or email and this password.":"បានកំណត់ពាក្យសម្ងាត់។ ឥឡូវអ្នកក៏អាចចូលដោយឈ្មោះអ្នកប្រើ ឬអ៊ីមែល និងពាក្យសម្ងាត់នេះបានដែរ។",
"You sign in with Google, so you do not need a recovery code.":"អ្នកចូលដោយ Google ដូច្នេះមិនត្រូវការលេខកូដសង្គ្រោះទេ។",
})


# Customer portal v25 (views/portal.py)
KH.update({
"My dashboard":"ផ្ទាំងរបស់ខ្ញុំ", "Pay":"បង់ប្រាក់", "Repayment schedule":"កាលវិភាគសងប្រាក់", "Apply for a loan":"ស្នើសុំកម្ចី",
"Messages":"សារ", "My documents":"ឯកសាររបស់ខ្ញុំ", "Profile & security":"ប្រវត្តិរូប និងសុវត្ថិភាព", "Help":"ជំនួយ",
"Hello":"សួស្តី", "Last sign-in":"ចូលចុងក្រោយ", "today":"ថ្ងៃនេះ", "tomorrow":"ថ្ងៃស្អែក", "Welcome to Credit Desk":"សូមស្វាគមន៍មកកាន់ Credit Desk", "You have no loan with us yet. Apply for one below.":"អ្នកមិនទាន់មានកម្ចីនៅឡើយ។ អាចស្នើសុំខាងក្រោម។",
"All your loans are fully repaid":"កម្ចីទាំងអស់របស់អ្នកបានសងរួចរាល់", "Thank you for banking with us.":"សូមអរគុណដែលបានប្រើសេវាយើង។",
"You are late on a payment":"អ្នកយឺតការបង់ប្រាក់", "Overdue amount":"ប្រាក់ហួសកំណត់",
"Pay now to stop late fees and protect your credit record.":"សូមបង់ឥឡូវ ដើម្បីបញ្ឈប់ពិន័យ និងការពារប្រវត្តិឥណទានរបស់អ្នក។",
"Your next payment is due soon":"ការបង់ប្រាក់បន្ទាប់ជិតដល់ហើយ", "You are up to date - thank you!":"អ្នកបង់ទាន់ពេល - សូមអរគុណ!",
"Every payment so far has been received.":"ការបង់ប្រាក់ទាំងអស់បានទទួលរួចរាល់។", "Pay now with KHQR":"បង់ឥឡូវតាម KHQR",
"See my schedule":"មើលកាលវិភាគ", "Amount to pay":"ប្រាក់ត្រូវបង់", "overdue":"ហួសកំណត់",
"next instalment":"ការបង់បន្ទាប់", "Due date":"ថ្ងៃត្រូវបង់", "days late":"ថ្ងៃយឺត", "on schedule":"តាមកាលវិភាគ",
"Principal remaining":"ប្រាក់ដើមនៅសល់", "Months remaining":"ខែនៅសល់", "Loan ends":"កម្ចីបញ្ចប់",
"You have repaid":"អ្នកបានសង", "of the money you borrowed":"នៃប្រាក់ដែលបានខ្ចី", "Debt-free on":"រួចពីបំណុលនៅ",
"pay it off early to save about":"បង់ផ្តាច់មុនដើម្បីសន្សំប្រហែល", "Repaid loans":"កម្ចីដែលបានសងរួច", "fully repaid":"បានសងរួច",
"Latest updates":"ព័ត៌មានថ្មីៗ", "No updates yet.":"មិនទាន់មានព័ត៌មានថ្មី។", "See all notifications":"មើលការជូនដំណឹងទាំងអស់",
"Payment record":"ប្រវត្តិការបង់ប្រាក់", "payments on time":"ការបង់ទាន់ពេល",
"Excellent payer - 1 year on time":"អ្នកបង់ល្អឥតខ្ចោះ - ទាន់ពេល ១ ឆ្នាំ", "Reliable payer":"អ្នកបង់ទៀងទាត់",
"Building your record":"កំពុងកសាងប្រវត្តិ", "Needs attention":"ត្រូវយកចិត្តទុកដាក់",
"Make a payment":"បង់ប្រាក់", "Payments":"ការបង់ប្រាក់", "How much do you want to pay?":"តើអ្នកចង់បង់ប៉ុន្មាន?",
"Everything overdue":"ប្រាក់ហួសកំណត់ទាំងអស់", "Next instalment":"ការបង់បន្ទាប់", "Overdue + next instalment":"ហួសកំណត់ + ការបង់បន្ទាប់",
"Pay off the whole loan":"បង់ផ្តាច់កម្ចីទាំងមូល", "Another amount":"ចំនួនផ្សេង", "Create KHQR code":"បង្កើត KHQR",
"Pay off early?":"បង់ផ្តាច់មុន?", "Pay-off amount today (estimate)":"ប្រាក់បង់ផ្តាច់ថ្ងៃនេះ (ប៉ាន់ស្មាន)",
"Scan and pay":"ស្កេន និងបង់", "Simulate a successful payment (demo)":"ធ្វើត្រាប់ការបង់ជោគជ័យ (demo)", "Cancel":"បោះបង់",
"Payment successful":"ការបង់ប្រាក់ជោគជ័យ", "Receipt":"វិក្កយបត្រ", "Principal repaid":"ប្រាក់ដើមបានសង", "Interest paid":"ការប្រាក់បានបង់",
"Still overdue":"នៅហួសកំណត់", "Download receipt (PDF)":"ទាញយកវិក្កយបត្រ (PDF)", "Done":"រួចរាល់",
"Having trouble paying? Ask the bank for help":"ពិបាកបង់? សុំជំនួយពីធនាគារ", "Send to my loan officer":"ផ្ញើទៅមន្ត្រីឥណទាន",
"My loans":"កម្ចីរបស់ខ្ញុំ", "Every instalment, what is paid and what is still to come.":"ការបង់នីមួយៗ អ្វីដែលបានបង់ និងអ្វីដែលនឹងមកដល់។",
"Paid":"បានបង់", "Overdue":"ហួសកំណត់", "Upcoming":"នឹងមកដល់", "All instalments":"ការបង់ទាំងអស់", "Instalment":"ប្រាក់ត្រូវបង់",
"Principal":"ប្រាក់ដើម", "Interest":"ការប្រាក់", "Balance after":"សមតុល្យនៅសល់", "Download schedule (PDF)":"ទាញយកកាលវិភាគ (PDF)",
"1 · Loan calculator":"១ · ម៉ាស៊ីនគណនាកម្ចី", "2 · Does it fit my budget?":"២ · តើសមនឹងថវិការបស់ខ្ញុំទេ?", "3 · Send my request":"៣ · ផ្ញើសំណើ",
"My monthly income ($)":"ប្រាក់ចំណូលប្រចាំខែ ($)", "Looks affordable":"អាចបង់បាន", "Send my request":"ផ្ញើសំណើ", "My requests":"សំណើរបស់ខ្ញុំ",
"Submitted":"បានផ្ញើ", "Under review":"កំពុងពិនិត្យ", "Decision":"ការសម្រេច", "Money issued":"បានបើកប្រាក់",
"Statements, schedules and receipts - ready to download.":"របាយការណ៍ កាលវិភាគ និងវិក្កយបត្រ - រួចរាល់សម្រាប់ទាញយក។",
"Loan statement":"របាយការណ៍កម្ចី", "Pay-off letter":"លិខិតបញ្ជាក់បង់ផ្តាច់", "Payment receipts":"វិក្កយបត្របង់ប្រាក់",
"Payments, reminders, decisions and replies.":"ការបង់ប្រាក់ ការរំលឹក ការសម្រេច និងការឆ្លើយតប។",
"Sign-in and security":"ការចូល និងសុវត្ថិភាព", "Recent sign-ins":"ការចូលថ្មីៗ", "Signed in":"បានចូល", "Signed out":"បានចាកចេញ",
"Questions and answers":"សំណួរ និងចម្លើយ", "Money words made simple":"ពាក្យហិរញ្ញវត្ថុងាយយល់", "Contact the bank":"ទាក់ទងធនាគារ",
})


# Customer portal v25 - payments, help, profile (second batch)
KH.update({
"A new schedule agreed with the bank when you have difficulty paying.":"កាលវិភាគថ្មីដែលព្រមព្រៀងជាមួយធនាគារ ពេលអ្នកពិបាកបង់។",
"Amount (USD)":"ចំនួនប្រាក់ (USD)",
"Answers to common questions, simple words, and how to reach us.":"ចម្លើយសំណួរទូទៅ ពាក្យងាយៗ និងរបៀបទាក់ទងយើង។",
"Approved by two bank officers - the money is being prepared.":"បានអនុម័តដោយមន្ត្រីពីរនាក់ - កំពុងរៀបចំប្រាក់។",
"Approved by your loan officer. A second officer is doing the final check (four-eyes rule) before the money is issued.":"មន្ត្រីឥណទានបានអនុម័តហើយ។ មន្ត្រីទីពីរកំពុងពិនិត្យចុងក្រោយ (ច្បាប់ភ្នែកបួន) មុនពេលបើកប្រាក់។",
"Attach":"ភ្ជាប់", "Automatic checking stopped. Press 'I have paid - check now' after paying.":"ការពិនិត្យស្វ័យប្រវត្តិបានឈប់។ សូមចុច 'ខ្ញុំបានបង់ - ពិនិត្យឥឡូវ' ក្រោយពេលបង់។",
"Available when the loan is fully repaid":"មានពេលសងកម្ចីរួចរាល់",
"Bakong has not received this payment yet. Wait a few seconds and check again.":"Bakong មិនទាន់ទទួលការបង់នេះទេ។ សូមរង់ចាំបន្តិច ហើយពិនិត្យម្តងទៀត។",
"Bring your loan up to date - your on-time record starts growing again from the next payment.":"សូមបង់ឲ្យទាន់ - ប្រវត្តិបង់ទាន់ពេលរបស់អ្នកនឹងចាប់ផ្តើមកើនឡើងវិញពីការបង់បន្ទាប់។",
"Business is slow":"អាជីវកម្មយឺត", "Can I pay off my loan early?":"តើខ្ញុំអាចបង់ផ្តាច់កម្ចីមុនបានទេ?",
"Change password, email or two-step sign-in":"ប្តូរពាក្យសម្ងាត់ អ៊ីមែល ឬការចូលពីរជំហាន",
"Check the amount and confirm":"ពិនិត្យចំនួនប្រាក់ ហើយបញ្ជាក់",
"Complete your profile (name, phone, address) before sending a request.":"សូមបំពេញប្រវត្តិរូប (ឈ្មោះ ទូរស័ព្ទ អាសយដ្ឋាន) មុនផ្ញើសំណើ។",
"Create a new code":"បង្កើតកូដថ្មី", "Describe the purpose and tick the box.":"សូមសរសេរគោលបំណង ហើយធីកប្រអប់។",
"Documents":"ឯកសារ", "Documents appear here once you have a loan.":"ឯកសារនឹងបង្ហាញនៅទីនេះ ពេលអ្នកមានកម្ចី។",
"Download schedule (Excel / CSV)":"ទាញយកកាលវិភាគ (Excel / CSV)",
"Estimate only: remaining principal plus interest already due. The bank confirms the exact amount.":"គ្រាន់តែជាការប៉ាន់ស្មាន៖ ប្រាក់ដើមនៅសល់ បូកការប្រាក់ដែលដល់កំណត់។ ធនាគារនឹងបញ្ជាក់ចំនួនពិត។",
"Expires in":"ផុតកំណត់ក្នុង", "First approval":"ការអនុម័តទី ១", "Head office":"ការិយាល័យកណ្តាល", "Hours":"ម៉ោងធ្វើការ",
"How do I pay with KHQR?":"តើខ្ញុំបង់តាម KHQR ដូចម្តេច?", "How is my interest calculated?":"តើការប្រាក់គណនាដូចម្តេច?",
"I forgot my password.":"ខ្ញុំភ្លេចពាក្យសម្ងាត់។", "I have paid - ask the bank to confirm":"ខ្ញុំបានបង់ហើយ - សុំធនាគារបញ្ជាក់",
"I have paid - check now":"ខ្ញុំបានបង់ហើយ - ពិនិត្យឥឡូវ", "Illness or family emergency":"ឈឺ ឬមានអាសន្នក្នុងគ្រួសារ",
"In Documents. Every payment has its own PDF receipt.":"នៅក្នុងឯកសារ។ ការបង់នីមួយៗមានវិក្កយបត្រ PDF ផ្ទាល់។",
"Instalments that were due but are not paid yet.":"ការបង់ដែលដល់កំណត់ ប៉ុន្តែមិនទាន់បង់។",
"Keep it up: customers with 12 on-time months can ask for a lower rate on their next loan.":"បន្តដូច្នេះ៖ អតិថិជនដែលបង់ទាន់ពេល ១២ ខែ អាចស្នើអត្រាការប្រាក់ទាបជាងសម្រាប់កម្ចីបន្ទាប់។",
"Loan closed":"កម្ចីបានបិទ", "Lost income / job":"បាត់ប្រាក់ចំណូល / ការងារ", "Meaning":"អត្ថន័យ",
"Message from the bank":"សារពីធនាគារ", "Next due":"ថ្ងៃបង់បន្ទាប់", "No notifications yet.":"មិនទាន់មានការជូនដំណឹង។",
"No sign-ins recorded yet.":"មិនទាន់មានការចូលដែលបានកត់ត្រា។",
"Not you? Change your password now in My account and tell the bank in Messages.":"មិនមែនអ្នក? សូមប្តូរពាក្យសម្ងាត់ក្នុង គណនីខ្ញុំ ហើយប្រាប់ធនាគារក្នុង សារ។",
"On the sign-in page press 'Forgot password?' - we email you a 6-digit code. If you signed up with Google, just press Continue with Google.":"នៅទំព័រចូល ចុច 'Forgot password?' - យើងផ្ញើលេខកូដ ៦ ខ្ទង់ទៅអ៊ីមែល។ បើអ្នកចុះឈ្មោះដោយ Google គ្រាន់តែចុច Continue with Google។",
"Open ABA Mobile, ACLEDA or any bank app":"បើក ABA Mobile, ACLEDA ឬ App ធនាគារណាមួយ",
"Open Pay, choose the amount, press Create KHQR code and scan it with ABA, ACLEDA, Wing or any Cambodian bank app. Your receipt appears straight away and the bank is told automatically.":"បើក បង់ប្រាក់ ជ្រើសចំនួន ចុច បង្កើត KHQR ហើយស្កេនដោយ ABA, ACLEDA, Wing ឬ App ធនាគារណាមួយ។ វិក្កយបត្របង្ហាញភ្លាម ហើយធនាគារទទួលដំណឹងដោយស្វ័យប្រវត្តិ។",
"Other monthly debt payments ($)":"ការបង់បំណុលផ្សេងទៀតប្រចាំខែ ($)", "Overdue / arrears":"ហួសកំណត់ / ប្រាក់យឺត",
"Password changed":"បានប្តូរពាក្យសម្ងាត់", "Password reset":"បានកំណត់ពាក្យសម្ងាត់ឡើងវិញ",
"Pay now to bring your loan up to date and protect your credit record.":"សូមបង់ឥឡូវ ដើម្បីឲ្យកម្ចីទាន់ពេល និងការពារប្រវត្តិឥណទានរបស់អ្នក។",
"Pay on time for":"បង់ទាន់ពេលរយៈពេល",
"Pay with any Cambodian bank app that scans KHQR (ABA, ACLEDA, Wing ...).":"បង់ដោយ App ធនាគារណាមួយដែលស្កេន KHQR បាន (ABA, ACLEDA, Wing ...)។",
"Pay-off amount":"ប្រាក់បង់ផ្តាច់",
"Paying on this same phone? Save the QR, then in ABA tap Scan → Gallery and choose it.":"បង់នៅលើទូរស័ព្ទដដែល? រក្សាទុក QR រួចក្នុង ABA ចុច Scan → Gallery ហើយជ្រើសវា។",
"Possible - the bank will look closely":"អាចធ្វើបាន - ធនាគារនឹងពិនិត្យយ៉ាងល្អិត", "Profile complete":"ប្រវត្តិរូបបានបំពេញ",
"Quick check only - not a decision. A loan officer reviews every request.":"គ្រាន់តែជាការពិនិត្យរហ័ស - មិនមែនជាការសម្រេចទេ។ មន្ត្រីឥណទានពិនិត្យរាល់សំណើ។",
"Request confirmations":"លិខិតបញ្ជាក់សំណើ", "Request sent":"បានផ្ញើសំណើ", "Restructure":"រៀបចំកម្ចីឡើងវិញ",
"Save QR to my phone":"រក្សាទុក QR ក្នុងទូរស័ព្ទ", "School demo":"Demo សម្រាប់សាលា",
"Second approval (four-eyes)":"ការអនុម័តទី ២ (ភ្នែកបួន)", "Send a message to my loan officer":"ផ្ញើសារទៅមន្ត្រីឥណទានរបស់ខ្ញុំ",
"Sent. Your loan officer will reply in Messages.":"បានផ្ញើ។ មន្ត្រីឥណទាននឹងឆ្លើយក្នុង សារ។",
"Share of income for debts":"ភាគរយប្រាក់ចំណូលសម្រាប់បំណុល", "Sign-in email":"អ៊ីមែលចូលគណនី", "Signed out (idle)":"បានចាកចេញ (អសកម្ម)",
"Tap Scan and point at the QR":"ចុច Scan ហើយតម្រង់ទៅ QR", "Tell us more":"ប្រាប់យើងបន្ថែម",
"Test mode: the QR charges":"Test mode៖ QR គិតប្រាក់", "Test payment":"ការបង់សាកល្បង",
"The bank has been notified automatically - no need to send a screenshot.":"ធនាគារបានទទួលដំណឹងដោយស្វ័យប្រវត្តិ - មិនបាច់ផ្ញើរូបថតទេ។",
"The bank will never ask for your password or a code we emailed you.":"ធនាគារមិនដែលសុំពាក្យសម្ងាត់ ឬលេខកូដដែលយើងផ្ញើទៅអ៊ីមែលរបស់អ្នកទេ។",
"The fixed amount you pay each month (principal + interest).":"ចំនួនថេរដែលអ្នកបង់រៀងរាល់ខែ (ប្រាក់ដើម + ការប្រាក់)។",
"The information I give is true.":"ព័ត៌មានដែលខ្ញុំផ្តល់ជាការពិត។",
"The instalment shows as overdue, your on-time record stops growing and the bank's collection team contacts you. Pay as soon as you can, or ask for help in Messages - the bank can agree a new date or a new schedule.":"ការបង់បង្ហាញថាហួសកំណត់ ប្រវត្តិបង់ទាន់ពេលឈប់កើន ហើយក្រុមប្រមូលបំណុលនឹងទាក់ទងអ្នក។ សូមបង់ឲ្យបានឆាប់ ឬសុំជំនួយក្នុង សារ - ធនាគារអាចព្រមព្រៀងថ្ងៃថ្មី ឬកាលវិភាគថ្មី។",
"The money you borrowed.":"ប្រាក់ដែលអ្នកបានខ្ចី។", "The price of borrowing, paid every month.":"ថ្លៃនៃការខ្ចី ដែលបង់រៀងរាល់ខែ។",
"This QR code has expired. Create a new one.":"QR នេះផុតកំណត់ហើយ។ សូមបង្កើតថ្មី។",
"Too high - try a smaller amount or a longer term":"ខ្ពស់ពេក - សូមសាកចំនួនតិចជាង ឬរយៈពេលវែងជាង",
"Try the calculator, check if it fits your budget, then send your request.":"សាកម៉ាស៊ីនគណនា ពិនិត្យថាសមនឹងថវិកា រួចផ្ញើសំណើ។",
"Two-step sign-in":"ការចូលពីរជំហាន", "Updates":"ព័ត៌មានថ្មី", "Schedule":"កាលវិភាគ", "Upload (PDF, JPG, PNG)":"ផ្ទុកឡើង (PDF, JPG, PNG)",
"Upload your documents below to speed it up.":"សូមផ្ទុកឯកសារខាងក្រោម ដើម្បីឲ្យលឿនជាងមុន។",
"Waiting for your payment":"កំពុងរង់ចាំការបង់របស់អ្នក", "We received your payment":"យើងបានទទួលការបង់របស់អ្នក",
"What happened?":"មានរឿងអ្វីកើតឡើង?", "What happens if I pay late?":"បើខ្ញុំបង់យឺត នឹងមានអ្វីកើតឡើង?",
"What you pay today to close the loan completely.":"ចំនួនដែលអ្នកបង់ថ្ងៃនេះ ដើម្បីបិទកម្ចីទាំងស្រុង។",
"Where are my receipts?":"វិក្កយបត្ររបស់ខ្ញុំនៅឯណា?", "Word":"ពាក្យ", "Wrong password":"ពាក្យសម្ងាត់ខុស",
"Yes. Open Pay and choose 'Pay off the whole loan'. You pay the remaining principal plus interest already due, and save the future interest.":"បាទ/ចាស។ បើក បង់ប្រាក់ ហើយជ្រើស 'បង់ផ្តាច់កម្ចីទាំងមូល'។ អ្នកបង់ប្រាក់ដើមនៅសល់ បូកការប្រាក់ដែលដល់កំណត់ ហើយសន្សំការប្រាក់អនាគត។",
"You have no loan to pay right now.":"អ្នកមិនមានកម្ចីត្រូវបង់ឥឡូវទេ។", "You have no loan yet.":"អ្នកមិនទាន់មានកម្ចីទេ។",
"Your details, your photo and who signed in to your account.":"ព័ត៌មាន រូបថត និងអ្នកដែលបានចូលគណនីរបស់អ្នក។",
"Your loan uses a fixed monthly instalment. Each payment first pays the interest for the month, the rest reduces the money you borrowed (the principal). As the principal falls, more of each payment goes to principal.":"កម្ចីរបស់អ្នកមានការបង់ប្រចាំខែថេរ។ ការបង់នីមួយៗបង់ការប្រាក់ខែនោះមុន ហើយនៅសល់កាត់បន្ថយប្រាក់ដើម។ ពេលប្រាក់ដើមថយចុះ ការបង់កាន់តែច្រើនទៅលើប្រាក់ដើម។",
"Your receipt is in My documents.":"វិក្កយបត្ររបស់អ្នកមាននៅក្នុង ឯកសាររបស់ខ្ញុំ។",
"Your sign-in email is changed in My account.":"អ៊ីមែលចូលគណនីត្រូវប្តូរនៅក្នុង គណនីខ្ញុំ។",
"banks usually look for 40% or less":"ធនាគារជាធម្មតាចង់បាន ៤០% ឬតិចជាង", "but records":"ប៉ុន្តែកត់ត្រា",
"estimate":"ប៉ាន់ស្មាន", "flat":"ថេរ", "has been cancelled.":"ត្រូវបានលុបចោល។", "instead of":"ជំនួសឲ្យ",
"more month(s) to reach the next badge.":"ខែទៀត ដើម្បីទទួលស្លាកបន្ទាប់។", "still scheduled":"នៅតាមកាលវិភាគ",
"you save about":"អ្នកសន្សំបានប្រហែល", "Two-step sign-in":"ការចូលពីរជំហាន",
"Monday-Friday 8:00-16:00 · Saturday 8:00-11:30":"ច័ន្ទ-សុក្រ ៨:០០-១៦:០០ · សៅរ៍ ៨:០០-១១:៣០",
"No. 61, Preah Monivong Blvd, Phnom Penh":"ផ្ទះលេខ ៦១ មហាវិថីព្រះមុនីវង្ស ភ្នំពេញ",
})


def t(text):
    if not isinstance(text,str) or st.session_state.get("customer_language","en") != "km":
        return text
    if text in KH:
        return KH[text]
    # Translate UI phrases within dynamic labels while preserving numbers/references.
    pattern = r"(?<![A-Za-z])(" + "|".join(re.escape(k) for k in sorted(KH,key=len,reverse=True)) + r")(?![A-Za-z])"
    return re.sub(pattern,lambda match: KH[match.group(0)],text)


def language_picker(render=True):
    mobile_styles()
    from src import auth, customer_portal as portal
    user = auth.current_user()
    if not user:
        return
    conn = portal.connect()
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS customer_preferences (username TEXT PRIMARY KEY, language TEXT NOT NULL DEFAULT 'en')")
        if st.session_state.get("_language_owner") != user.username:
            row = conn.execute("SELECT language FROM customer_preferences WHERE username=?",(user.username,)).fetchone()
            st.session_state["customer_language"] = row[0] if row and row[0] in {"en","km"} else "en"
            st.session_state["_language_owner"] = user.username
        if not render:
            return
        choice = st.sidebar.selectbox("Language / ភាសា",["en","km"],format_func=lambda code: "English" if code == "en" else "ខ្មែរ",key="customer_language")
        conn.execute("INSERT INTO customer_preferences VALUES (?,?) ON CONFLICT(username) DO UPDATE SET language=excluded.language WHERE language!=excluded.language",(user.username,choice))
    finally:
        conn.close()
