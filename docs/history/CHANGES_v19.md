# v19 - ready to host on the web

No feature changed. Only how the app is started on a hosting service.

- `.streamlit/config.toml`: no longer pins the app to this computer (`address = 127.0.0.1`), so a host
  can serve it. The START launcher (`launch.py`) still binds it to this computer when run locally.
- `app.py`: reads `CREDIT_DESK_*` settings from the hosting service's Secrets box
  (`.streamlit/secrets.toml`). A real environment variable still wins.
- `.streamlit/secrets.toml.example`: the settings you can paste into Secrets.
- `Dockerfile`: listens on the port the host assigns (`$PORT`, 8501 otherwise).
- `HOW TO HOST.md`: Streamlit Community Cloud step by step (English and Khmer), safety settings,
  Docker hosts.

Checked: plain `streamlit run app.py` on all network interfaces (as a host runs it) answers on the
network address; Secrets switch off the trial accounts and set the admin password; the Docker start
command answers its health check on a host-assigned port; 195 tests pass.
