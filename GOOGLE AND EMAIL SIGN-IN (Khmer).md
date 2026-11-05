# ការចូលគណនីដោយ Google និង Email · Credit Desk v25

## ✅ អ្វីដែលបានដាក់រួចហើយ
- file **`.streamlit/secrets.toml`** មាន **Client ID** និង **Client secret** របស់ Google (ពី file JSON របស់អ្នក) រួចហើយ
- Gmail **`thetortor6969@gmail.com`** ក្លាយជា **Administrator** ដោយស្វ័យប្រវត្តិ នៅពេលចុច **Continue with Google** លើកដំបូង
- file `secrets.toml` **មិនត្រូវបាន push ទៅ GitHub ទេ** (មានក្នុង `.gitignore`)។ **កុំផ្ញើ file នេះឲ្យអ្នកណា**

## 🚀 របៀបបើក
1. ចុចពីរដងលើ **START Credit Desk (Windows).bat**។ លើកដំបូង វានឹងដំឡើង **Authlib** (ត្រូវការអ៊ីនធឺណិត)
2. App ត្រូវតែបើកនៅ **http://localhost:8501**។ បើវាសរសេរថា *"port 8501 is busy"* សូមបិទវិនដូរ Credit Desk ផ្សេងទៀតសិន ព្រោះ Google ទទួលតែ port **8501** ប៉ុណ្ណោះ
3. នៅលើទំព័រ Sign in ចុច **Continue with Google** → ជ្រើស Gmail → ចូលដោយស្វ័យប្រវត្តិ

## 👥 តួនាទីពេលចូលដោយ Google
| Gmail | តួនាទី |
| --- | --- |
| `thetortor6969@gmail.com` | **Administrator** |
| Gmail ផ្សេងទៀត (លើកដំបូង) | **Customer** (ដូចការចុះឈ្មោះធម្មតា) |
| Gmail ដែល Admin បានដាក់ក្នុង **User management** | តួនាទីដែល Admin ជ្រើស (Officer, Risk...) |

**ដើម្បីឲ្យមិត្តក្រុមជា Officer ឬ Risk:** Admin ចូល **User management** → **Add a user** → បញ្ចូល Gmail → ជ្រើស Role → ធីក **Google sign-in only** → **Create user**។ បន្ទាប់មក មិត្តក្រុមគ្រាន់តែចុច **Continue with Google**។

⚠️ **Test users:** Google App របស់អ្នកស្ថិតក្នុងស្ថានភាព **Testing**។ មានតែ Gmail ដែលបានបញ្ចូលក្នុង **Google Cloud Console → Google Auth Platform → Audience → Test users** ប៉ុណ្ណោះ ដែលអាចចូលបាន។ បើមិនបានបញ្ចូលទេ នឹងចេញ **"Access blocked"**។

## 🔐 ទំព័រ Sign in ថ្មី (ផ្ទាំងតែមួយ)
- **Continue with Google** ឬវាយ **username ឬ email** និងពាក្យសម្ងាត់
- ក្រោមប្រអប់ពាក្យសម្ងាត់មាន **Forgot password?** → បញ្ចូល email → ទទួល**លេខកូដ ៦ ខ្ទង់** → បញ្ចូលលេខកូដ និងពាក្យសម្ងាត់ថ្មី → **ចូល App ភ្លាម**
- ប៊ូតុង **Sign in** និង **Sign up** នៅជាប់គ្នា។ **Sign up** បើកទម្រង់ចុះឈ្មោះ (Google ឬ email) → ផ្ទៀងផ្ទាត់ email ដោយលេខកូដ → **Continue to Credit Desk**
- **Trial mode** (មិនទាន់មាន Gmail App Password): លេខកូដបង្ហាញលើអេក្រង់ក្នុងប្រអប់ពណ៌លឿង ជំនួសការផ្ញើ email ដើម្បីងាយ demo។ ពេលដាក់ `[email]` ក្នុង `secrets.toml` រួច លេខកូដនឹងផ្ញើទៅ email ពិត

## 👤 My account
- បង្ហាញ email, ស្ថានភាព **Verified / Not verified**, និងវិធីចូល (**Google ✓**, **Password ✓**)
- **ប្តូរ email** និង**ផ្ទៀងផ្ទាត់** ដោយ **Verify with Google** ឬ **Email me a code**
- អ្នកប្រើ Google អាច **Set a password** (ជម្រើសបន្ថែម)

## 📧 (ជម្រើសបន្ថែម) ផ្ញើលេខកូដតាម Email
បើចង់ឲ្យ **Forgot password** និង **Create account** ផ្ញើលេខកូដ ៦ ខ្ទង់ទៅ email៖
1. បង្កើត Gmail សម្រាប់ project (ឧ. `creditdesk.g4@gmail.com`)
2. បើក **2-Step Verification** → បង្កើត **App password** (១៦ អក្សរ)
3. បើក `.streamlit/secrets.toml` ដោយ Notepad ហើយលុប `# ` នៅមុខបន្ទាត់ក្នុងផ្នែក `[email]` រួចបញ្ចូល Gmail និង App password
4. បិទ ហើយបើក Credit Desk ម្តងទៀត

## 🌐 បើ host លើ Streamlit Cloud
1. ក្នុង Google Console → **Clients** → បន្ថែម redirect URI: `https://ឈ្មោះ-app.streamlit.app/oauth2callback`
2. Copy ខ្លឹមសារ `secrets.toml` ទៅប្រអប់ **Secrets** របស់ Streamlit Cloud ហើយប្តូរ `redirect_uri` ទៅ link ខាងលើ

## ❓ បញ្ហាដែលអាចកើតមាន
| បញ្ហា | ដំណោះស្រាយ |
| --- | --- |
| **Access blocked / access_denied** | បញ្ចូល Gmail ក្នុង **Test users** |
| **redirect_uri_mismatch** | App មិនបានបើកនៅ port **8501** ឬ redirect URI ក្នុង Google Console ខុស |
| មិនឃើញប៊ូតុង **Continue with Google** | មិនទាន់ដំឡើង Authlib (ចុច START ម្តងទៀត) ឬ `secrets.toml` បាត់ |
| ចូលដោយ Google ហើយឃើញ **Customer** | Admin ប្តូរ Role ក្នុង **User management** |
