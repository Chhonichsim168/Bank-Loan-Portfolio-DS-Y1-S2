"""Run by tests/test_v16.py in its own process: open every page with the optional libraries hidden
(as on a computer where they were never installed), using a throw-away data folder."""
import os
import sys
import tempfile

ROOT = sys.argv[1]
sys.path.insert(0, ROOT)
t = tempfile.mkdtemp()
os.environ.update(CREDIT_DESK_AUDIT_DB=t + "/a.db", CREDIT_DESK_AUDIT_FALLBACK=t + "/f.jsonl",
                  CREDIT_DESK_USERS_FILE=t + "/u.json", CREDIT_DESK_DOC_DIR=t + "/d",
                  CREDIT_DESK_MODEL_DIR=t + "/m", CREDIT_DESK_SAMPLE_DATA="0")
from streamlit.testing.v1 import AppTest  # noqa: E402

PAGE = "\n".join([
    "import sys",
    "for m in ('cryptography', 'reportlab', 'openpyxl', 'matplotlib'):",
    "    sys.modules[m] = None",
    "sys.path.insert(0, r'{root}')",
    "import streamlit as st",
    "from src import auth, state, ui",
    "ui.inject_theme(); state.init()",
    "st.session_state['_auth_user'] = auth.User('tester', 'Tester', 'admin')",
    "from views import {mod}",
    "{mod}.render()",
])
bad = []
for mod in ["governance", "segments", "model", "batch", "queue", "loan_book", "underwrite"]:
    at = AppTest.from_string(PAGE.format(root=ROOT, mod=mod), default_timeout=300).run()
    if at.exception:
        bad.append(f"{mod}: {at.exception[0].value[:200]}")
print("FAILED:" + " | ".join(bad))
