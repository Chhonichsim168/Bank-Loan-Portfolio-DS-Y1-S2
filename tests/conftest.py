"""Shared fixtures: every test gets its own throw-away audit DB, user file, model folder and
upload folder, so tests never touch (or depend on) real data."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture()
def sandbox(tmp_path, monkeypatch):
    from src import audit, auth, policy_store

    monkeypatch.setattr(audit, "DB_PATH", tmp_path / "audit.db")
    monkeypatch.setattr(audit, "FALLBACK_PATH", tmp_path / "audit_fallback.jsonl")
    monkeypatch.setattr(auth, "USERS_FILE", tmp_path / "users.json")
    monkeypatch.setattr(auth, "FIRST_RUN_FILE", tmp_path / "first_run.txt")
    monkeypatch.setattr(policy_store, "UPLOAD_DIR", tmp_path / "uploads")
    from src import documents
    monkeypatch.setattr(documents, "DOC_DIR", tmp_path / "documents")
    monkeypatch.setenv("CREDIT_DESK_MODEL_DIR", str(tmp_path / "models"))
    monkeypatch.delenv("CREDIT_DESK_SINGLE_OPERATOR", raising=False)
    # Most tests exercise the multi-user controls (roles, four-eyes); tests/test_no_login.py
    # covers the default no-sign-in mode.
    monkeypatch.setenv("CREDIT_DESK_REQUIRE_LOGIN", "1")
    # ...and the strict security options, which are off by default (tests/test_simple_login.py
    # covers the defaults).
    monkeypatch.setenv("CREDIT_DESK_LOCKOUT", "1")
    monkeypatch.setenv("CREDIT_DESK_STRONG_PASSWORDS", "1")
    monkeypatch.setenv("CREDIT_DESK_DEMO_USERS", "0")
    monkeypatch.setenv("CREDIT_DESK_SAMPLE_DATA", "0")      # tests/test_sample_data.py turns it on
    monkeypatch.setenv("CREDIT_DESK_AUTO_LOGOUT", "1")
    monkeypatch.delenv("CREDIT_DESK_REQUIRE_MFA", raising=False)
    monkeypatch.delenv("CREDIT_DESK_ADMIN_PASSWORD", raising=False)
    return tmp_path
