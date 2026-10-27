# How to put Credit Desk on the web

The free and easiest way is **Streamlit Community Cloud**: it runs the app straight from your
GitHub repository and gives it a web address such as `https://credit-desk-g4.streamlit.app`.

## Before you start
- The latest code is pushed to GitHub (`git add .` / `git commit` / `git push`).
- `app.py` is at the top level of the repository (it is in this project).
- You can sign in to GitHub. If the repository belongs to an organisation (for example the class
  organisation) and is **private**, the organisation owner (your teacher) may have to allow
  Streamlit to read it - or make the repository **public**.

## Steps (about 10 minutes)
1. Open **https://share.streamlit.io** and choose **Continue with GitHub**. Allow access.
2. Click **Create app** (top right) and choose **Yup, I have an app**.
3. Fill in:
   | Field | Value |
   |---|---|
   | Repository | `tonghengkeo-aub/aub-batch-10-y1-s2-a-g4-Bank-Loan-Portfolio-Analytics` |
   | Branch | `main` |
   | Main file path | `app.py` |
   | App URL (optional) | a short name, e.g. `credit-desk-g4` |
4. Open **Advanced settings**:
   - **Python version**: choose **3.13** (the version the tests use).
   - **Secrets**: leave empty for the class demo (simple accounts admin/admin123...), or paste lines
     from `.streamlit/secrets.toml.example` (see "Safety" below).
   Click **Save**.
5. Click **Deploy**. Installing takes about 3-5 minutes. The very first page load then trains the
   model and loads the sample data (about 1 minute). After that the app opens in seconds.
6. Share the web address with your teacher and team. Every `git push` updates the site by itself.

## Good to know
- **Data on the website is temporary.** Decisions, loans and payments you enter online are kept
  while the app is running, but are reset when the app restarts, is re-deployed or wakes up from
  sleep (the sample data loads again). For permanent data run it on a computer or a server with
  a disk (Docker, below).
- **Sleeping:** if nobody opens the app for a while it goes to sleep. The next visitor clicks
  "Yes, get this app back up" and waits about a minute.
- **Changing a setting later:** share.streamlit.io > your app > **Settings > Secrets**. The app
  restarts with the new settings.

## Safety on a public address
Anyone with the link can open the sign-in page. With the default settings the sign-in page shows
the simple trial passwords. That is fine for a class demo with sample data only.
For anything more, paste this into **Secrets** before the first start:
```toml
CREDIT_DESK_DEMO_USERS = "0"
CREDIT_DESK_ADMIN_PASSWORD = "choose-a-long-password-here"
CREDIT_DESK_LOCKOUT = "1"
```
Then only `admin` with your password can sign in (you are asked to replace it at first sign-in),
the trial hint is hidden, and an account locks for 15 minutes after 5 wrong passwords. Create
accounts for the team under **Administration > User management**.
Never put real customer data on a demo site.

## Other hosts (Docker)
The `Dockerfile` runs the app on any host that runs containers (Render, Railway, Fly.io, a VPS).
It listens on the port the host gives in `$PORT` (8501 otherwise) and keeps its data in
`/app/data` - attach a disk/volume there so data survives restarts. Settings are passed as
environment variables with the same names as in `.streamlit/secrets.toml.example`.

---

# ខ្មែរ — របៀបដាក់ Credit Desk លើវេបសាយ

1. Push កូដចុងក្រោយទៅ GitHub។
2. បើក **share.streamlit.io** → **Continue with GitHub**។
3. ចុច **Create app** → **Yup, I have an app**។
4. បំពេញ៖ Repository = repository របស់ក្រុម, Branch = `main`, Main file path = `app.py`, App URL = ឈ្មោះខ្លី (ឧ. `credit-desk-g4`)។
5. **Advanced settings** → Python version = **3.13** → **Save**។
6. ចុច **Deploy** → រង់ចាំ 3–5 នាទី → បើកលើកដំបូងរង់ចាំបន្ថែមប្រហែល 1 នាទី។
7. ចែករំលែក link ឲ្យគ្រូ និងក្រុម។ រាល់ពេល `git push` វេបសាយ update ដោយខ្លួនឯង។

ចំណាំ៖ ទិន្នន័យដែលបញ្ចូលលើវេបសាយ នឹងត្រលប់ទៅទិន្នន័យគំរូវិញ ពេលកម្មវិធី restart ឬភ្ញាក់ពីការដេក។
បើ repository ជា private ក្នុង organization គ្រូប្រហែលជាត្រូវអនុញ្ញាតឲ្យ Streamlit ចូលអាន ឬប្តូរ repository ទៅជា public។
