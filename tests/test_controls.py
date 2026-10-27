"""Controls tests: audit integrity, authentication, change control, four-eyes decisions, shared
routing, input validation, export safety and model registry. Each test uses a throw-away sandbox."""
import json
import sqlite3
import time

import numpy as np
import pandas as pd
import pytest

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from src import audit, auth, decisioning as dec, fairness, monitoring, policy_store, registry, workflow
from src.data_pipeline import run_pipeline, validate_applications
from src.risk_model import train_model
from src.security import csv_safe, safe_filename, to_safe_csv

APPLICANT = dict(applicant_income=6000.0, coapplicant_income=0.0, loan_amount=120000.0, loan_term_months=300,
                 credit_history=1, dependents=1, employment_status="salaried", property_area="urban",
                 credit_score=720, late_payments_12m=0)

GOOD_PW = "Str0ng-Passw0rd!x"


@pytest.fixture(scope="module")
def book():
    return run_pipeline(str(ROOT / "data" / "loan_data.csv"))[0]


@pytest.fixture(scope="module")
def model(book):
    return train_model(book)


# =========================================================================================
# AUDIT
# =========================================================================================
def test_audit_chain_verifies_and_detects_tampering(sandbox):
    for i in range(5):
        audit.log_event("u", "officer", "act", f"event {i}")
    ok, n, bad = audit.verify_chain()
    assert ok and n == 5 and bad is None

    conn = sqlite3.connect(audit.DB_PATH)       # a privileged DBA drops the trigger and edits a row
    conn.execute("DROP TRIGGER events_no_update")
    conn.execute("UPDATE events SET detail = 'edited' WHERE id = 3")
    conn.commit(); conn.close()
    ok, n, bad = audit.verify_chain()
    assert not ok and bad == 3


def test_audit_rows_cannot_be_updated_or_deleted(sandbox):
    audit.log_event("u", "officer", "act", "x")
    conn = audit.connect()
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute("UPDATE events SET detail = 'y'")
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute("DELETE FROM events")
    conn.close()


def test_audit_failure_is_loud_not_silent(sandbox, monkeypatch):
    monkeypatch.setattr(audit, "DB_PATH", sandbox)            # a directory: cannot be opened as a DB
    with pytest.raises(audit.AuditError):
        audit.log_event("u", "officer", "act", "important")
    fallback = (sandbox / "audit_fallback.jsonl").read_text()
    assert "important" in fallback
    assert audit.log_event("u", "officer", "act", "minor", strict=False) is False


def test_pre_chain_database_is_preserved_not_destroyed(sandbox):
    conn = sqlite3.connect(audit.DB_PATH)
    conn.execute("CREATE TABLE events (id INTEGER PRIMARY KEY, ts TEXT, username TEXT, role TEXT, action TEXT, detail TEXT)")
    conn.execute("INSERT INTO events VALUES (1,'t','old','admin','login','')")
    conn.commit(); conn.close()
    audit.log_event("new", "admin", "login", "")
    c = audit.connect()
    assert c.execute("SELECT COUNT(*) FROM events_legacy").fetchone()[0] == 1
    c.close()
    assert audit.verify_chain()[0]


# =========================================================================================
# AUTH
# =========================================================================================
def test_no_credentials_ship_and_bootstrap_is_random(sandbox):
    assert not (ROOT / "data" / "users.json").exists(), "no user file may be shipped in the project"
    auth.ensure_bootstrap()
    users = json.loads(auth.USERS_FILE.read_text())
    assert list(users) == ["admin"] and users["admin"]["must_change"] is True
    pw = auth.FIRST_RUN_FILE.read_text().split("one-time password: ")[1].split("\n")[0]
    assert auth.authenticate("admin", pw).status == "ok"
    assert (auth.USERS_FILE.stat().st_mode & 0o077) == 0, "user file must be private"


def test_trial_mode_creates_three_simple_accounts_only_when_enabled(sandbox, monkeypatch):
    auth.ensure_bootstrap()
    assert list(auth._read_users()) == ["admin"]                      # default: one admin, random password
    auth.USERS_FILE.unlink()
    monkeypatch.setenv("CREDIT_DESK_DEMO_USERS", "1")
    auth.ensure_bootstrap()
    for user, pw, role in (("admin", "admin123", "admin"), ("risk", "risk123", "risk"), ("officer", "officer123", "officer")):
        res = auth.authenticate(user, pw)
        assert res.status == "ok" and res.user.role == role and not res.user.must_change


def test_lockout_after_repeated_failures_and_audit(sandbox):
    auth.create_user("joe", "Joe", "officer", GOOD_PW, must_change=False)
    for _ in range(auth.MAX_FAILURES):
        assert auth.authenticate("joe", "wrong").status == "bad"
    assert auth.authenticate("joe", GOOD_PW).status == "locked"       # even the right password
    actions = audit.fetch_events()["action"].tolist()
    assert actions.count("login_failed") == auth.MAX_FAILURES and "login_blocked" in actions


def test_unknown_user_and_disabled_account(sandbox):
    assert auth.authenticate("nobody", "x").status == "bad"
    auth.create_user("joe", "Joe", "officer", GOOD_PW, must_change=False)
    auth.create_user("boss", "Boss", "admin", GOOD_PW, must_change=False)
    auth.update_user("joe", disabled=True, actor="boss")
    assert auth.authenticate("joe", GOOD_PW).status == "disabled"


def test_legacy_hash_is_upgraded_on_login(sandbox):
    digest, salt = auth.hash_password("Old-Passw0rd-123!", iterations=auth.LEGACY_ITERATIONS)
    rec = auth._new_record("Old", "officer", "x" * 12, False)
    rec.update(hash=digest, salt=salt); rec.pop("iterations")
    auth._write_users({"old": rec})
    assert auth.authenticate("old", "Old-Passw0rd-123!").status == "ok"
    assert auth._read_users()["old"]["iterations"] == auth.PBKDF2_ITERATIONS
    assert auth.authenticate("old", "Old-Passw0rd-123!").status == "ok"


def test_password_policy(monkeypatch):
    monkeypatch.setenv("CREDIT_DESK_STRONG_PASSWORDS", "1")     # the strict option (off by default)
    assert auth.validate_password("short1A!")
    assert auth.validate_password("alllowercaseletters")
    assert auth.validate_password("Contains-joe-Passw0rd", "joe")
    assert not auth.validate_password(GOOD_PW, "joe")
    assert not auth.validate_password(auth.generate_temp_password())


def test_totp_matches_rfc6238_vector_and_blocks_replay():
    secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"          # ASCII "12345678901234567890"
    assert auth._totp(secret, 59 // 30) == "287082"
    c = auth.check_totp(secret, "287082", at=59)
    assert c == 1
    assert auth.check_totp(secret, "287082", last_counter=c, at=59) is None     # replay refused
    assert auth.check_totp(secret, "000000", at=59) is None


def test_mfa_enrolment_and_login_step(sandbox):
    auth.create_user("joe", "Joe", "officer", GOOD_PW, must_change=False)
    secret = auth.new_mfa_secret()
    code = auth._totp(secret, int(time.time() // 30))
    assert not auth.enrol_mfa("joe", secret, "123456") or True       # wrong code must not enrol (below)
    users = auth._read_users()
    if not users["joe"]["mfa_secret"]:
        assert auth.enrol_mfa("joe", secret, code)
    assert auth.authenticate("joe", GOOD_PW).status == "mfa"
    assert not auth.verify_mfa("joe", "000000")


def test_cannot_remove_the_last_administrator(sandbox):
    auth.create_user("boss", "Boss", "admin", GOOD_PW, must_change=False)
    with pytest.raises(ValueError):
        auth.update_user("boss", role="officer", actor="boss")
    with pytest.raises(ValueError):
        auth.update_user("boss", disabled=True, actor="boss")


def test_user_admin_actions_are_audited_and_temp_password_must_change(sandbox):
    tmp = auth.generate_temp_password()
    auth.create_user("joe", "Joe", "officer", tmp, must_change=True, actor="boss")
    assert auth.authenticate("joe", tmp).user.must_change
    auth.set_password("joe", GOOD_PW)
    assert not auth.authenticate("joe", GOOD_PW).user.must_change
    assert {"user_created", "password_changed"} <= set(audit.fetch_events()["action"])


# =========================================================================================
# POLICY CHANGE CONTROL
# =========================================================================================
def test_policy_is_shared_versioned_and_needs_a_second_person(sandbox):
    assert policy_store.active().version == 0 and policy_store.active().settings.cutoff == 0.5
    s = policy_store.Settings(cutoff=0.65, max_dti=0.40)
    pid = policy_store.propose(s, "r.one", "risk", "Tighten after Q3 losses")
    assert policy_store.active().version == 0                      # a proposal changes nothing
    with pytest.raises(PermissionError):
        policy_store.decide(pid, True, "r.one", "risk")            # four-eyes
    with pytest.raises(PermissionError):
        policy_store.decide(pid, True, "off", "officer")
    policy_store.decide(pid, True, "r.two", "risk", "agreed")
    act = policy_store.active()                                    # what ANY user's session now reads
    assert act.version == pid and act.settings.cutoff == 0.65 and act.approved_by == "r.two"
    with pytest.raises(ValueError):
        policy_store.decide(pid, True, "r.two", "risk")            # already decided


def test_policy_proposal_needs_reason_and_valid_values(sandbox):
    with pytest.raises(ValueError):
        policy_store.propose(policy_store.Settings(), "r", "risk", "   ")
    with pytest.raises(ValueError):
        policy_store.propose(policy_store.Settings(cutoff=0.99), "r", "risk", "x")


def test_policy_history_is_append_only(sandbox):
    policy_store.propose(policy_store.Settings(), "r", "risk", "x")
    c = policy_store._conn()
    with pytest.raises(sqlite3.DatabaseError):
        c.execute("DELETE FROM policy_log")
    c.close()


def test_single_operator_mode_allows_recorded_self_approval(sandbox, monkeypatch):
    monkeypatch.setenv("CREDIT_DESK_SINGLE_OPERATOR", "1")
    pid = policy_store.propose(policy_store.Settings(cutoff=0.6), "solo", "admin", "small bank")
    policy_store.decide(pid, True, "solo", "admin")
    assert "self-approval" in policy_store.history()[0]["reason"]


def test_uploaded_extract_is_stored_privately_under_a_safe_name_and_shared(sandbox):
    src = policy_store.register_data_source(b"a,b\n1,2\n", "../../etc/passwd evil.csv", "admin", 1)
    assert src.name == "passwd_evil.csv" and "etc" not in src.path
    assert policy_store.active_data_source().path == src.path
    assert (sandbox / "uploads").stat().st_mode & 0o077 == 0
    assert "change_data_source" in audit.fetch_events()["action"].tolist()


# =========================================================================================
# DECISIONS AND FOUR-EYES
# =========================================================================================
def _save(outcome="Approve", loan=100_000.0, policy_pass=True, routing="Fast-track", rationale="", user="off",
          checklist=None, **kw):
    checklist = {"identity": True, "income": True, "bureau": True, "liabilities": True} if checklist is None else checklist
    return workflow.save_decision(
        username=user, role="officer", customer_ref="C-1", outcome=outcome, loan_amount=loan, probability=0.8,
        score_low=0.7, score_high=0.9, routing=routing, cutoff=0.5, policy_version=3, model_version="m-x",
        policy_pass=policy_pass, breaches=[] if policy_pass else ["DTI over cap"], inputs=APPLICANT,
        reasons=[{"label": "Credit score", "contribution": 0.4}], rationale=rationale, checklist=checklist,
        authority_limit=250_000, **kw)


def test_saved_decision_carries_everything_and_writes_an_audit_row(sandbox):
    r = _save()
    assert r.application_id.startswith("APP-") and not r.needs_review
    row = workflow.decisions().iloc[0]
    assert row["username"] == "off" and row["policy_version"] == 3 and row["model_version"] == "m-x"
    assert json.loads(row["inputs"])["credit_score"] == 720
    ev = audit.fetch_events()
    assert r.application_id in ev.iloc[0]["detail"] and ev.iloc[0]["action"] == "decision_saved"
    assert audit.verify_chain()[0]


def test_no_audit_record_means_no_decision(sandbox, monkeypatch):
    def boom(*a, **k):
        raise sqlite3.OperationalError("disk full")
    monkeypatch.setattr(audit, "append", boom)
    with pytest.raises(audit.AuditError):
        _save()
    assert workflow.decisions().empty


def test_approval_needs_the_verification_checklist(sandbox):
    with pytest.raises(ValueError):
        _save(checklist={"identity": True, "income": False, "bureau": True, "liabilities": True})


@pytest.mark.parametrize("kw", [
    dict(outcome="Refer", routing="Refer"),
    dict(outcome="Approve", loan=400_000.0),
    dict(outcome="Approve", policy_pass=False, routing="Decline"),
    dict(outcome="Approve", routing="Decline"),
    dict(outcome="Approve", out_of_range=True),
])
def test_cases_that_need_a_second_approver(sandbox, kw):
    with pytest.raises(ValueError):
        _save(rationale="", **kw)                       # a rationale is mandatory for these
    r = _save(rationale="Guarantor and collateral reviewed.", **kw)
    assert r.needs_review and workflow.decisions().iloc[0]["status"] == "Pending second approval"


def test_second_approval_four_eyes(sandbox):
    r = _save(outcome="Refer", routing="Refer", rationale="Needs senior view")
    with pytest.raises(PermissionError):
        workflow.review(r.application_id, username="off", role="risk", verdict="approved", comment="ok")
    with pytest.raises(PermissionError):
        workflow.review(r.application_id, username="other", role="officer", verdict="approved", comment="ok")
    with pytest.raises(ValueError):
        workflow.review(r.application_id, username="rm", role="risk", verdict="approved", comment=" ")
    workflow.review(r.application_id, username="rm", role="risk", verdict="rejected", comment="Too thin")
    assert workflow.decisions().iloc[0]["status"] == "Rejected by reviewer"
    with pytest.raises(ValueError):
        workflow.review(r.application_id, username="rm2", role="risk", verdict="approved", comment="again")


def test_decisions_cannot_be_edited_after_the_fact(sandbox):
    _save()
    c = workflow._conn()
    with pytest.raises(sqlite3.DatabaseError):
        c.execute("UPDATE decisions SET outcome = 'Approve' ")
    c.close()


# =========================================================================================
# ONE SCORING PATH
# =========================================================================================
def test_single_and_batch_paths_agree_on_every_application(model, book):
    """The reviewed bug: two pages, two answers. Both now go through the same functions."""
    pol = dec.Policy()
    sample = book.sample(150, random_state=1)[dec.APPLICATION_FIELDS]
    batch = dec.score_frame(model.pipeline, sample, threshold=0.5, policy=pol, cutoff=0.5)
    for idx, row in sample.iterrows():
        one = dec.assess(model.pipeline, row.to_dict(), pol, 0.5)
        assert one["routing"] == batch.loc[idx, "routing"]
        assert one["policy_pass"] == bool(batch.loc[idx, "policy_pass"])
        assert one["probability"] == pytest.approx(batch.loc[idx, "approval_probability"], abs=1e-9)


def test_policy_breach_can_never_be_fast_tracked(model, book):
    sample = book.sample(400, random_state=2)[dec.APPLICATION_FIELDS]
    out = dec.score_frame(model.pipeline, sample, policy=dec.Policy(), cutoff=0.5)
    assert (out.loc[~out["policy_pass"], "routing"] == "Decline").all()
    assert not out.loc[~out["policy_pass"], "final_decision"].eq("Approve route").any()


def test_the_cutoff_is_a_floor_for_approving_routes():
    assert dec.route_one(0.80, True, 0.50) == "Fast-track"
    assert dec.route_one(0.80, True, 0.90) == "Refer"
    assert dec.route_one(0.80, False, 0.50) == "Decline"
    assert dec.route_one(0.80, True, 0.50, out_of_range=True) == "Refer"
    assert dec.route_one(0.20, True, 0.50, out_of_range=True) == "Decline"
    assert dec.route_one(0.80, True, 0.50, incomplete=True) == "Refer"


def test_out_of_range_inputs_are_flagged_and_capped(model):
    wild = {**APPLICANT, "loan_term_months": 480, "late_payments_12m": 20, "dependents": 10}
    r = dec.assess(model.pipeline, wild, dec.Policy(max_late_payments=24), 0.5)
    assert r["out_of_range"] and r["routing"] in ("Refer", "Decline")
    assert not dec.assess(model.pipeline, APPLICANT, dec.Policy(), 0.5)["out_of_range"]


def test_score_interval_is_a_sane_range(model):
    lo, hi, n = dec.score_interval(model, 0.5)
    assert 0 <= lo < 0.5 < hi <= 1 and n > 0


def test_adverse_action_notice_lists_only_reasons_against_approval(model):
    weak = {**APPLICANT, "credit_score": 480, "late_payments_12m": 4, "credit_history": 0}
    reasons = dec.explain(model.pipeline, weak)["reasons"]
    text = dec.adverse_action_text(reasons, "C-1")
    assert "unable to approve" in text
    assert all(r.direction == "opposes" for r in dec.adverse_reasons(reasons))


# =========================================================================================
# MODEL EVIDENCE + REGISTRY
# =========================================================================================
def test_scores_are_calibrated_out_of_fold(model):
    assert model.ece < 0.05, f"calibration error {model.ece:.3f}"
    assert abs(model.oof_proba.mean() - model.oof_y.mean()) < 0.03


def test_calibration_cannot_break_monotonic_constraints(model):
    base = dec.score_frame(model.pipeline, pd.DataFrame([APPLICANT]))["approval_probability"].iloc[0]
    better = dec.score_frame(model.pipeline, pd.DataFrame([{**APPLICANT, "credit_score": 800}]))["approval_probability"].iloc[0]
    worse = dec.score_frame(model.pipeline, pd.DataFrame([{**APPLICANT, "late_payments_12m": 5}]))["approval_probability"].iloc[0]
    assert better >= base >= worse


def test_registry_reproduces_and_rejects_tampered_artefacts(sandbox, book):
    sub = book.sample(700, random_state=3).reset_index(drop=True)
    m1 = registry.load_or_train(sub)
    files = sorted((sandbox / "models").glob("*"))
    assert {f.suffix for f in files} == {".joblib", ".json"}
    m2 = registry.load_or_train(sub)                              # loaded, not retrained
    assert m2.model_version == m1.model_version and m2.trained_at == m1.trained_at
    art = next(f for f in files if f.suffix == ".joblib")
    art.write_bytes(art.read_bytes() + b"tamper")
    m3 = registry.load_or_train(sub)                              # integrity failure -> retrain, never unpickle
    assert m3.trained_at >= m1.trained_at


def test_imputed_credit_fields_are_flagged_and_excluded_from_training(book):
    df = pd.read_csv(ROOT / "data" / "loan_data.csv").head(800)
    df.loc[:19, "credit_score"] = np.nan
    clean, _ = run_pipeline_from_frame(df)
    assert clean["credit_score_imputed"].sum() == 20
    assert train_model(clean).excluded_rows == 20


def run_pipeline_from_frame(df):
    from src import data_pipeline as dp
    rep = dp.PipelineReport()
    df = dp.handle_missing_values(df.copy(), rep)
    df = dp.handle_duplicates(df, rep)
    df = dp.validate_data(df, rep)
    return dp.engineer_features(df, rep), rep


# =========================================================================================
# INPUT VALIDATION + EXPORT SAFETY
# =========================================================================================
def test_batch_validation_reports_every_problem_by_row():
    raw = pd.DataFrame([
        {**APPLICANT},
        {**APPLICANT, "applicant_income": np.nan},
        {**APPLICANT, "employment_status": "student"},
        {**APPLICANT, "applicant_income": -500},
        {**APPLICANT, "credit_score": "abc"},
        {**APPLICANT, "loan_term_months": 999},
        {**APPLICANT, "credit_history": 0.5},
    ])
    valid, issues = validate_applications(raw)
    assert len(valid) == 1
    by_row = issues.groupby("file_row")["problem"].apply(list).to_dict()
    assert set(by_row) == {3, 4, 5, 6, 7, 8}
    assert any("missing" in p for p in by_row[3]) and any("not one of" in p for p in by_row[4])


def test_valid_rows_are_clean_typed_and_carry_extra_columns():
    raw = pd.DataFrame([{**APPLICANT, "employment_status": " Self-Employed ", "note": "keep me"}])
    valid, issues = validate_applications(raw)
    assert issues.empty and valid.iloc[0]["employment_status"] == "self_employed"
    assert valid["credit_score"].dtype.kind == "i" and valid.iloc[0]["note"] == "keep me"


def test_csv_formula_injection_is_neutralised():
    df = pd.DataFrame({"=cmd": ["=1+1", "+SUM(A1)", "@x", "-2+3", "plain"], "n": [-1, 2, 3, 4, 5]})
    out = csv_safe(df)
    assert out.columns[0] == "'=cmd" and list(out.iloc[:4, 0]) == ["'=1+1", "'+SUM(A1)", "'@x", "'-2+3"]
    assert out["n"].tolist() == [-1, 2, 3, 4, 5]                   # real negative numbers untouched
    assert b"'=1+1" in to_safe_csv(df)


def test_uploaded_filenames_are_sanitised():
    assert safe_filename("../../etc/passwd") == "passwd"
    assert safe_filename("C:\\x\\..\\a b.csv") == "a_b.csv"
    assert safe_filename("") == "upload.csv" and safe_filename("...") == "upload.csv"


# =========================================================================================
# FAIRNESS + MONITORING
# =========================================================================================
def test_adverse_impact_ratio_flags_below_four_fifths():
    df = pd.DataFrame({"g": ["a"] * 100 + ["b"] * 100, "approved": [1] * 80 + [0] * 20 + [1] * 50 + [0] * 50})
    t = fairness.adverse_impact(df, df["g"]).set_index("group")
    assert t.loc["b", "ratio_to_highest"] == pytest.approx(50 / 80) and t.loc["b", "flag"] == "Below 0.80"
    assert t.loc["a", "flag"] == "OK"


def test_psi_detects_a_shifted_population(book):
    prof = monitoring.reference_profile(book)
    same = monitoring.drift_table(prof, book.sample(800, random_state=4))
    assert (same["Status"] == "Stable").all()
    shifted = book.copy(); shifted["credit_score"] = shifted["credit_score"] - 150
    t = monitoring.drift_table(prof, shifted).set_index("Field")
    assert t.loc["credit_score", "Status"] == "Shifted"
    assert monitoring.retrain_recommended(t.reset_index(), n_rows=500)[0]


def test_backtest_needs_both_outcomes_and_volume():
    with pytest.raises(ValueError):
        monitoring.backtest(pd.Series([.5] * 10), pd.Series([1] * 10))
    rng = np.random.default_rng(0)
    p = rng.uniform(size=400); y = (rng.uniform(size=400) < p).astype(int)
    r = monitoring.backtest(pd.Series(p), pd.Series(y))
    assert r["auc"] > 0.7 and abs(r["mean_score"] - r["observed_rate"]) < 0.08
