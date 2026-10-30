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
