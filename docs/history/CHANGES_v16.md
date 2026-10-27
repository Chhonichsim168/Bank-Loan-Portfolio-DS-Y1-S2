# Credit Desk v16

| Request | What changed | Where |
|---|---|---|
| Data and governance errors (Backup, Lineage, Risk scoring rule) | One cause: the launcher installed only 5 libraries, so `cryptography` (and `reportlab`, `openpyxl`, `matplotlib`) were missing; Streamlit runs every tab, so the Backup crash showed at the bottom of every tab. The launcher now installs all of them, and every page opens even if one is missing (a yellow note says what to install). | Run app.bat, START Credit Desk.command, src/deps.py |
| Approval drivers chart | Approval-rate line is drawn on top of the bars (it was hidden behind them), thicker, with bold labels; 3.5x line in the scatter is thicker; scatter zoomed. | views/drivers.py |
| Clear text boxes | Every text, number, date, dropdown and text-area box has an outlined white box; upload areas a dashed outline; green buttons have white text. | src/ui.py |
| Sample loan book | 18 loans: matured and repaid, settled early, written off (2), matured but unpaid, maturing soon, new loans due in 4 and 10 days, current, 1-29 / 30-59 / 60-89 / 90+ days late, restructured, partial payment, promise to pay. | src/sample_data.py |
| Sample decision queue | 24 decisions: 4 waiting (2 past the 2-day target), approved / rejected / returned by reviewer, final approvals and declines, a repeat applicant, 3 approvals ready for "Add a loan". | src/sample_data.py |
| Sample documents | Download buttons for a sample of every document type (Identity JPG, Income proof PDF, Bank statement PDF, Collateral PNG, Contract PDF, Other PDF) in Supporting documents. | views/_docs.py, data/sample_documents/ |
| Auto sign-out | Toggle under Sign out; OFF by default; saved per user. | app.py, src/auth.py |

Sample records start with `SAMPLE-`, load once on first start, and never twice. For real use set
`CREDIT_DESK_SAMPLE_DATA=0` in Run app.bat before the first start. Tests: 184 passed.
