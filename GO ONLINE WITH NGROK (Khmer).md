# បើក Credit Desk ឲ្យអតិថិជនចូលពីទូរស័ព្ទ (ngrok · ឥតគិតថ្លៃ)

ngrok ផ្តល់ **link ថេរមួយ** (ឧ. `https://credit-desk-g4.ngrok-free.app`) ដែលភ្ជាប់ទៅ Credit Desk នៅលើកុំព្យូទ័ររបស់អ្នក។
Google sign-in, email, KHQR + Bakong (IP កម្ពុជា) និងទិន្នន័យ នៅតែដំណើរការដូចពេល run លើកុំព្យូទ័រ។

## ជំហានទី 1 · ចុះឈ្មោះ ngrok (តែម្តង)
1. ចូល **https://ngrok.com** → **Sign up** (ឥតគិតថ្លៃ)
2. **Domains** → ចម្លង link ថេររបស់អ្នក (ឧ. `credit-desk-g4.ngrok-free.app`)
3. **Download** → ទាញយក ngrok សម្រាប់ Windows → unzip → ដាក់ **`ngrok.exe`** ក្នុង folder **Credit_Desk** (ជាប់នឹង `app.py`)
4. **Your Authtoken** → copy → បើក `cmd` ក្នុង folder Credit_Desk ហើយវាយ៖
   ```
   ngrok config add-authtoken ដាក់-authtoken-របស់អ្នក
   ```

## ជំហានទី 2 · ដាក់ link ក្នុង secrets.toml (តែម្តង)
បើក `.streamlit\secrets.toml` ដោយ Notepad → នៅបន្ទាត់ខាងលើ (មុន `[auth]`) ដាក់៖
```toml
CREDIT_DESK_PUBLIC_DOMAIN = "credit-desk-g4.ngrok-free.app"
```

## ជំហានទី 3 · បន្ថែម link ក្នុង Google (តែម្តង)
Google Cloud Console → **Google Auth Platform → Clients → Credit Desk web** → **Authorized redirect URIs** → **+ Add URI**:
```
https://credit-desk-g4.ngrok-free.app/oauth2callback
```
(ទុក `http://localhost:8501/oauth2callback` ដដែល) → **Save**

## ជំហានទី 4 · បើក
ចុចពីរដងលើ **START Credit Desk ONLINE (Windows).bat**
- វាបើក Credit Desk + ngrok ហើយប្តូរ Google sign-in ទៅ link ថេរដោយស្វ័យប្រវត្តិ
- ផ្ញើ link `https://credit-desk-g4.ngrok-free.app` ឲ្យអតិថិជន → បើកលើទូរស័ព្ទបាន
- លើកដំបូង ngrok បង្ហាញទំព័រព្រមាន → ចុច **Visit Site**
- **កុំព្យូទ័រត្រូវបើក និងភ្ជាប់អ៊ីនធឺណិត**ពេលអតិថិជនប្រើ

ពេលចង់ប្រើតែលើកុំព្យូទ័រវិញ → ចុច **START Credit Desk (Windows).bat** ធម្មតា (វាប្តូរ Google ត្រឡប់ទៅ localhost ដោយខ្លួនឯង)។

## កម្រិតឥតគិតថ្លៃ
20,000 request / ខែ · 1 GB / ខែ ដែលគ្រប់គ្រាន់សម្រាប់ assignment និង demo។
