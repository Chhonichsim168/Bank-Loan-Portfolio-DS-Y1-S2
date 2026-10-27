"""Application data - the loan applications in the SQLite database: browse, add, remove.

Every chart, KPI and the model read this table, so a record added or removed here shows up on
Overview, Segments, Approval drivers, Policy and Model performance straight away."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from src import app_store, audit, auth, ui
from src.data_pipeline import today_local
from src.security import to_safe_csv
from views import _result

TERMS = [12, 24, 36, 48, 60, 84, 120, 180, 240, 300, 360, 420, 480]
LABELS = {"id": "ID", "application_date": "Received", "applicant_income": "Income",
          "coapplicant_income": "Co-applicant income", "loan_amount": "Loan amount",
          "loan_term_months": "Term (months)", "credit_history": "Credit history", "dependents": "Dependents",
          "employment_status": "Employment", "property_area": "Area", "credit_score": "Credit score",
          "late_payments_12m": "Late payments 12m", "approved": "Approved", "added_by": "Added by",
          "added_ts": "Added at (UTC)"}


def render() -> None:
    user = auth.current_user()
    ui.page_header(
        "Application data",
        "The loan applications stored in the SQLite database. Every chart, KPI and the model are "
        "calculated from this table, so adding or removing a record updates them automatically.",
        eyebrow="Portfolio")

    df = app_store.load_frame(with_ids=True)
    by_user = df[df["added_by"] != "import"]
    c = st.columns(4, gap="small")
    with c[0]:
        ui.kpi("Records in the database", f"{len(df):,}", foot=f"table applications · {app_store.source_name()}")
    with c[1]:
        ui.kpi("Approved", f"{df['approved'].mean() * 100:.1f}%" if len(df) else "-",
               foot=f"{int(df['approved'].sum()):,} approved · {int((df['approved'] == 0).sum()):,} declined")
    with c[2]:
        ui.kpi("Added by users", f"{len(by_user):,}", foot="since the data was imported")
    with c[3]:
        ui.kpi("Removed", f"{len(app_store.deleted()):,}", foot="kept in the archive")

    t_browse, t_add, t_hist = st.tabs(["Browse and remove", "Add a record", "Removed records"])
    with t_browse:
        _browse(df, user)
    with t_add:
        _add(user)
    with t_hist:
        _removed()


# ---- browse + delete ----------------------------------------------------------------------
def _browse(df: pd.DataFrame, user) -> None:
    n = st.session_state.get("_ad_nonce", 0)       # new widget keys after each removal = empty boxes
    ui.section("Records", "Newest first. Tick the box at the start of a row to select it.")
    f1, f2, f3 = st.columns([1, 1, 1.2], gap="small")
    who = f1.selectbox("Show", ["All records", "Added by users", "Imported"], key="ad_show")
    outcome = f2.selectbox("Outcome", ["All", "Approved", "Declined"], key="ad_outcome")
    find = f3.text_input("Find ID", key="ad_find", placeholder="e.g. 2001")
    view = df.iloc[::-1]
    if who == "Added by users":
        view = view[view["added_by"] != "import"]
    elif who == "Imported":
        view = view[view["added_by"] == "import"]
    if outcome != "All":
        view = view[view["approved"] == (1 if outcome == "Approved" else 0)]
    if find.strip():
        view = view[view["id"].astype(str) == find.strip()]
    st.caption(f"{len(view):,} record(s) shown")

    shown = view.assign(approved=view["approved"].map({1: "Yes", 0: "No"}),
                        credit_history=view["credit_history"].map({1: "On file", 0: "None"}),
                        added_ts=view["added_ts"].fillna("").astype(str).str[:16])
    shown = shown.rename(columns=LABELS)
    can_delete = user.role in app_store.DELETE_ROLES
    sel = []
    if can_delete and hasattr(st, "dataframe"):
        try:
            event = st.dataframe(shown, hide_index=True, key=f"ad_table_{n}", on_select="rerun",
                                 selection_mode="multi-row", height=420, **ui.STRETCH)
            rows = event.selection.rows if event and hasattr(event, "selection") else []
            sel = [int(view.iloc[i]["id"]) for i in rows]
        except TypeError:                       # older Streamlit without row selection
            ui.table(shown, height=420)
    else:
        ui.table(shown, height=420)

    st.download_button("Download these records (CSV)", to_safe_csv(view.drop(columns=["added_ts"])),
                       file_name="applications.csv", mime="text/csv", key="ad_dl")

    ui.section("Remove records")
    if not can_delete:
        ui.note("Removing records is limited to a Risk Manager or Administrator, and every removal is "
                "kept in the audit log. You can add records on the next tab.", title="Read-only for this role",
                tone="info")
        return
    if sel != st.session_state.get("_ad_last_sel"):            # ticked rows fill the box
        st.session_state["_ad_last_sel"] = sel
        st.session_state[f"ad_del_ids_{n}"] = ", ".join(str(i) for i in sel)
    ids_text = st.text_input("Record ID(s) to remove", key=f"ad_del_ids_{n}",
                             help="Tick rows in the table above, or type IDs separated by commas.")
    try:
        ids = [int(x) for x in ids_text.replace(" ", "").split(",") if x]
    except ValueError:
        st.error("IDs must be whole numbers separated by commas.")
        return
    reason = st.text_input("Reason (required, kept in the audit log)", key=f"ad_del_reason_{n}")
    sure = st.checkbox(f"I understand that {len(ids)} record(s) will be removed from every chart and the model "
                       "(a copy is kept in Removed records).", key=f"ad_del_sure_{n}", disabled=not ids)
    if st.button(f"Remove {len(ids)} record(s)", type="primary", disabled=not (ids and sure), key="ad_del_go"):
        try:
            view_rows = df[df["id"].isin(ids)]
            n = app_store.delete(ids, user.username, user.role, reason)
            _result.push(
                title="Records removed", pdf_title="Application records removed", number=f"DEL-{min(ids)}",
                status=f"{n} record(s) removed - charts and the model now use {len(df) - n:,} records", tone="warn",
                rows=[("Records removed", ", ".join(f"#{i}" for i in ids[:30])), ("Reason", reason.strip()),
                      ("Removed by", f"{user.display_name} ({user.username})"),
                      ("Records left", f"{len(df) - n:,}")],
                table=view_rows.drop(columns=["added_ts"]).rename(columns=LABELS), table_title="Removed records",
                next_steps=["Open Overview or Segments: the charts already use the new data.",
                            "The model is re-trained on the first page that needs it (about 15 seconds)."],
                file_stem=f"removed_{min(ids)}")
            st.session_state["_ad_nonce"] = n + 1
            st.session_state.pop("_ad_last_sel", None)
            st.rerun()
        except (ValueError, PermissionError, audit.AuditError) as exc:
            st.error(str(exc))


# ---- add ------------------------------------------------------------------------------------
def _add(user) -> None:
    ui.section("Add an application record",
               "A past application and its outcome, added to the data the charts and the model learn from. "
               "To score a NEW customer, use Decisioning > Score an application instead.")
    today = today_local().date()
    num = dict(value=None, placeholder="Type a number")
    with st.form("ad_add", clear_on_submit=True, border=True):
        a, b, c = st.columns(3, gap="medium")
        with a:
            day = st.date_input("Application received", value=today, max_value=today, format="DD/MM/YYYY")
            inc = st.number_input("Monthly income", min_value=0.0, max_value=200_000.0, step=250.0, **num)
            coinc = st.number_input("Co-applicant monthly income", min_value=0.0, max_value=200_000.0, step=250.0,
                                    value=None, placeholder="0 if none")
            deps = st.number_input("Dependents", min_value=0, max_value=10, step=1, **num)
        with b:
            amount = st.number_input("Loan amount", min_value=1.0, max_value=5_000_000.0, step=1000.0, **num)
            term = st.selectbox("Term (months)", TERMS, index=None, placeholder="Choose a term")
            emp = st.selectbox("Employment", ["salaried", "self_employed", "unemployed"], index=None,
                               placeholder="Choose one", format_func=lambda v: v.replace("_", "-").title())
            area = st.selectbox("Property area", ["urban", "semiurban", "rural"], index=None,
                                placeholder="Choose one", format_func=lambda v: v.title())
        with c:
            hist = st.selectbox("Credit history", [1, 0], index=None, placeholder="Choose one",
                                format_func=lambda v: "On file" if v == 1 else "None or adverse")
            score = st.number_input("Credit score", min_value=300, max_value=850, step=5, **num)
            late = st.number_input("Late payments - last 12 months", min_value=0, max_value=24, step=1, **num)
            outcome = st.selectbox("Outcome", [1, 0], index=None, placeholder="Approved or declined?",
                                   format_func=lambda v: "Approved" if v == 1 else "Declined")
        go = st.form_submit_button("Add record", type="primary")
    if not go:
        return
    rec = {"application_date": day.isoformat() if day else None, "applicant_income": inc,
           "coapplicant_income": 0.0 if coinc is None else coinc, "loan_amount": amount,
           "loan_term_months": term, "credit_history": hist, "dependents": deps, "employment_status": emp,
           "property_area": area, "credit_score": score, "late_payments_12m": late, "approved": outcome}
    try:
        rid = app_store.add(rec, user.username, user.role)
        n = app_store.count()
        money = "{:,.2f}".format
        _result.push(
            title="Record added", pdf_title="Application record added", number=f"REC-{rid}",
            status=f"Saved in the database as record #{rid} - charts and the model now use {n:,} records",
            rows=[("Record", f"#{rid}"), ("Received", day.strftime("%d/%m/%Y")),
                  ("Monthly income", money(inc)), ("Co-applicant income", money(rec["coapplicant_income"])),
                  ("Loan amount", money(amount)), ("Term", f"{term} months"),
                  ("Credit history", "On file" if hist == 1 else "None or adverse"),
                  ("Dependents", str(deps)), ("Employment", emp.replace("_", "-").title()),
                  ("Property area", area.title()), ("Credit score", str(score)),
                  ("Late payments 12m", str(late)), ("Outcome", "Approved" if outcome == 1 else "Declined"),
                  ("Added by", f"{user.display_name} ({user.username})")],
            next_steps=["Open Overview or Segments: the charts already include this record.",
                        "The model is re-trained on the first page that needs it (about 15 seconds)."],
            file_stem=f"record_{rid}")
        st.rerun()
    except (ValueError, audit.AuditError) as exc:
        st.error(str(exc))


# ---- removed --------------------------------------------------------------------------------
def _removed() -> None:
    ui.section("Removed records", "Every removed record, who removed it, when and why. Kept for audit.")
    d = app_store.deleted()
    if d.empty:
        st.caption("No record has been removed.")
        return
    import json
    rows = pd.DataFrame([json.loads(s) for s in d["row_json"]]).drop(columns=["extra"], errors="ignore")
    out = pd.concat([d[["deleted_ts", "deleted_by", "reason"]].reset_index(drop=True), rows], axis=1)
    out["deleted_ts"] = out["deleted_ts"].astype(str).str[:16]
    ui.table(out.rename(columns={**LABELS, "deleted_ts": "Removed at (UTC)", "deleted_by": "Removed by",
                                 "reason": "Reason"}), height=360)
