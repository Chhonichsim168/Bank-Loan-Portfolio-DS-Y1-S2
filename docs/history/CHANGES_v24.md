# Credit Desk v24 — ready to host as a website; no menu on the sign-in page

Built on v23. No feature, page, calculation or data was changed.

* The sign-in page (before sign-in, and after Sign out) shows only the sign-in card: the sidebar
  and the "☰ Menu" button are hidden. The Menu button is created only after a successful
  sign-in, and removed again on Sign out (`app.py: _hide_menu_when_signed_out`).
* Hosting checked from a fresh copy started the way Streamlit Community Cloud starts it
  (`streamlit run app.py`, no local database): health check ok, sign-in, sign-out, Menu
  behaviour verified in a browser.
* New `HOW TO HOST (Khmer).md` - step-by-step hosting guide in Khmer.
* Tests: 250 passed.
