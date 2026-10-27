# របៀបដាក់ Credit Desk ជាគេហទំព័រ (Streamlit Community Cloud · ឥតគិតថ្លៃ)

## មុនចាប់ផ្តើម
1. Push កូដចុងក្រោយទៅ GitHub (`git add .` → `git commit -m "..."` → `git push origin main`)
2. ត្រូវប្រើគណនី GitHub **ម្ចាស់ repository** (`tonghengkeo-aub`) ព្រោះ Streamlit ទាមទារសិទ្ធិ **Admin**

## ជំហាន (ប្រហែល ១០ នាទី)
1. បើក **https://share.streamlit.io** → **Continue with GitHub** → Authorize
2. ចុច **Create app** → **Deploy a public app from GitHub** (ឬ "Yup, I have an app")
3. បំពេញ៖
   - Repository: `tonghengkeo-aub/aub-batch-10-y1-s2-a-g4-Bank-Loan-Portfolio-Analytics`
   - Branch: `main`
   - Main file path: `app.py`
   - App URL: ឧ. `credit-desk-g4`
4. **Advanced settings** → Python version **3.13** → Secrets ទុកទទេ (ប្រើគណនី admin/admin123, risk/risk123, officer/officer123) → **Save**
5. ចុច **Deploy** → រង់ចាំ ៣–៥ នាទី (ដំឡើង) + ១ នាទី (បើកលើកដំបូង៖ train ម៉ូដែល និងនាំចូលទិន្នន័យ 2,000 ទៅ SQLite)
6. ទទួលបាន link `https://credit-desk-g4.streamlit.app` → ផ្ញើឲ្យគ្រូ និងក្រុម

## ដឹងមុន
- **ទិន្នន័យ (SQLite)**៖ នៅជាប់ពេលកម្មវិធីកំពុងរត់ ប៉ុន្តែ **reset** ពេល restart, deploy ថ្មី (រាល់ `git push`) ឬភ្ញាក់ពីការដេក
- **កុំ push នៅថ្ងៃ Demo** · បើក link មុន ១៥ នាទី ដើម្បីដាស់កម្មវិធី
- **Reset ទិន្នន័យមុន Demo**៖ share.streamlit.io → ⋮ → **Reboot app**
- **កុំដាក់ទិន្នន័យអតិថិជនពិត** ព្រោះ link ជា public
- ចង់ប្តូរការកំណត់៖ share.streamlit.io → app → **Settings → Secrets** (មើល `.streamlit/secrets.toml.example`)
