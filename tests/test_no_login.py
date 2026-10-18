"""Optional mode (CREDIT_DESK_REQUIRE_LOGIN=0): no sign-in. The app opens straight away for one local operator, who can also
approve their own referrals and policy changes (there is no second person)."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def nologin(sandbox, monkeypatch):
    monkeypatch.setenv("CREDIT_DESK_REQUIRE_LOGIN", "0")
    return sandbox


def test_mode_defaults(nologin):
    from src.mode import login_required, single_operator
    assert not login_required() and single_operator()


def test_app_opens_without_a_login_page(nologin):
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=300).run()
    assert not at.exception, [e.value for e in at.exception]
    text = " ".join(m.value for m in at.markdown)
    assert "Portfolio overview" in text
    assert not at.text_input                    # no username / password boxes
    assert not any(b.label == "Sign out" for b in at.sidebar.button)
    from src import auth
    assert not auth.USERS_FILE.exists()          # no account file is created


def test_account_pages_are_hidden(nologin):
    from src import auth
    assert not auth.can_access("admin", "users") and not auth.can_access("admin", "account")
    assert auth.can_access("admin", "overview") and auth.can_access("admin", "policy")


def test_single_operator_can_approve_own_referral(nologin):
    from src import workflow
    workflow.save_decision(username="local", role="admin", customer_ref="C-1", outcome="Refer", loan_amount=1e4,
                           probability=0.5, score_low=0.4, score_high=0.6, routing="Refer", cutoff=0.5,
                           policy_version=0, model_version="m", policy_pass=True, breaches=[], inputs={},
                           reasons=[], rationale="x", checklist={}, authority_limit=2.5e5)
    app_id = workflow.decisions().iloc[0]["application_id"]
    workflow.review(app_id, username="local", role="admin", verdict="approved", comment="checked")
    assert workflow.decisions().iloc[0]["status"] == "Final (approved by reviewer)"


def test_single_operator_can_approve_own_policy_change(nologin):
    from src import policy_store
    s = policy_store.Settings(max_dti=0.40)
    pid = policy_store.propose(s, "local", "admin", "tighten DTI")
    policy_store.decide(pid, True, "local", "admin", "ok")
    assert policy_store.active().settings.max_dti == 0.40


def test_four_eyes_still_applies_when_sign_in_is_on(sandbox):
    from src import workflow
    workflow.save_decision(username="o1", role="officer", customer_ref="C-2", outcome="Refer", loan_amount=1e4,
                           probability=0.5, score_low=0.4, score_high=0.6, routing="Refer", cutoff=0.5,
                           policy_version=0, model_version="m", policy_pass=True, breaches=[], inputs={},
                           reasons=[], rationale="x", checklist={}, authority_limit=2.5e5)
    app_id = workflow.decisions().iloc[0]["application_id"]
    with pytest.raises(PermissionError):
        workflow.review(app_id, username="o1", role="admin", verdict="approved", comment="self")
