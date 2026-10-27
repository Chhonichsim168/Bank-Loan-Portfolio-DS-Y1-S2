"""Score a file — batch scoring for a day's intake."""

from __future__ import annotations

import io
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src import decisioning as dec
from src import ui
from src.data_pipeline import today_local, validate_applications

SLA_DAYS = 3        # an application should get a decision within this many days of receipt
from src.security import esc, to_safe_csv
from src.state import ctx
from src import auth, audit

MAX_UPLOAD_MB = 20
MAX_ROWS = 50_000

REQUIRED = dec.APPLICATION_FIELDS

# The file served by the "Download template" button. If it is missing, the two-row
# TEMPLATE below is used instead, so the button never breaks.
SAMPLE_PATH = Path(__file__).resolve().parent.parent / "data" / "application_sample_100.csv"

# 100 example applications built into the app, so the download button always works even
# when data/application_sample_100.csv is not present.
SAMPLE_CSV = """application_date,applicant_income,coapplicant_income,loan_amount,loan_term_months,credit_history,dependents,employment_status,property_area,credit_score,late_payments_12m
2026-10-05,6268,0,117000,300,1,2,salaried,rural,803,0
2026-10-02,4866,2282,75000,180,0,3,self_employed,rural,486,2
2026-10-02,3390,0,76000,360,1,0,salaried,urban,745,0
2026-10-02,4550,2374,139000,240,1,2,self_employed,rural,702,0
2026-10-13,5480,7800,114000,300,1,0,self_employed,rural,725,0
2026-10-14,6236,4192,159000,120,0,0,salaried,urban,559,1
2026-10-01,16635,3524,70000,360,0,2,unemployed,semiurban,453,3
2026-10-08,4284,0,121000,360,0,1,salaried,semiurban,566,2
2026-10-07,2845,2321,128000,300,0,3,salaried,rural,459,4
2026-10-06,1169,938,133000,360,0,1,salaried,rural,679,3
2026-10-12,3056,0,90000,360,0,0,salaried,rural,515,0
2026-10-02,5740,0,119000,300,0,0,self_employed,semiurban,530,4
2026-10-05,11564,0,117000,360,1,3,salaried,rural,745,0
2026-10-13,3307,2178,194000,360,1,2,self_employed,semiurban,804,1
2026-10-05,5786,3226,125000,360,0,1,self_employed,urban,470,0
2026-10-12,5653,0,166000,180,0,0,self_employed,urban,524,2
2026-10-15,4536,1130,55000,240,1,0,salaried,semiurban,708,1
2026-10-07,12024,3006,110000,360,1,1,salaried,urban,695,0
2026-10-14,6964,972,123000,360,1,0,salaried,rural,844,0
2026-10-09,3861,0,105000,360,1,0,self_employed,rural,717,1
2026-10-13,9278,1875,107000,360,0,2,self_employed,semiurban,638,6
2026-10-06,5316,0,98000,300,1,0,self_employed,semiurban,603,0
2026-10-16,9952,2107,228000,240,1,0,salaried,urban,803,0
2026-10-13,6907,420,111000,240,1,3,salaried,rural,689,0
2026-10-02,9194,4102,120000,360,1,0,self_employed,rural,708,1
2026-10-06,12092,997,77000,360,1,0,salaried,rural,703,0
2026-10-16,3578,0,138000,180,1,2,self_employed,semiurban,691,1
2026-10-13,3982,0,97000,360,1,2,salaried,semiurban,839,1
2026-10-14,4277,929,168000,120,1,0,salaried,urban,713,0
2026-10-01,9940,0,98000,360,1,0,salaried,urban,713,0
2026-10-05,3728,0,166000,360,0,3,salaried,urban,500,4
2026-10-07,4547,7036,105000,360,0,0,self_employed,urban,493,4
2026-10-09,4264,3589,134000,360,1,2,salaried,urban,826,0
2026-10-09,6217,788,134000,360,0,0,self_employed,rural,544,3
2026-10-16,2773,986,285000,300,1,1,salaried,urban,809,0
2026-10-06,1620,0,101000,240,1,0,salaried,rural,670,0
2026-10-07,4149,1163,96000,240,0,0,salaried,rural,663,6
2026-10-15,3921,0,109000,360,1,0,salaried,urban,752,0
2026-10-14,5155,0,103000,240,1,1,salaried,urban,616,0
2026-10-01,1862,806,155000,180,1,0,self_employed,urban,619,0
2026-10-08,6688,0,203000,180,0,0,self_employed,rural,526,3
2026-10-02,3297,0,138000,360,1,2,salaried,semiurban,779,0
2026-10-16,2581,936,87000,360,1,0,salaried,rural,688,0
2026-10-01,9090,483,51000,300,1,1,self_employed,urban,762,0
2026-10-13,3322,0,160000,360,1,1,salaried,urban,711,1
2026-10-06,2387,4498,68000,180,1,1,salaried,semiurban,609,0
2026-10-01,7771,213,58000,240,1,0,salaried,urban,726,0
2026-10-07,3747,4396,156000,300,1,1,salaried,rural,825,0
2026-10-16,6116,1628,184000,240,1,0,salaried,urban,761,0
2026-10-15,2288,0,69000,300,0,1,self_employed,semiurban,494,1
2026-10-05,1950,4637,153000,240,1,2,self_employed,semiurban,730,0
2026-10-07,5674,0,56000,180,1,1,salaried,urban,736,0
2026-10-08,2794,1374,104000,300,1,1,salaried,semiurban,736,0
2026-10-06,5075,1984,129000,360,0,0,self_employed,urban,573,0
2026-10-07,1843,1257,187000,360,1,0,salaried,semiurban,784,0
2026-10-13,3379,0,141000,360,1,2,self_employed,semiurban,687,0
2026-10-02,8286,6197,62000,360,1,0,self_employed,urban,618,1
2026-10-14,8134,2192,138000,360,1,2,salaried,semiurban,781,0
2026-10-01,14052,0,68000,300,0,0,self_employed,urban,647,5
2026-10-13,4495,1785,151000,120,1,3,salaried,semiurban,789,0
2026-10-16,6061,0,76000,240,1,2,salaried,urban,739,1
2026-10-16,2747,0,128000,240,0,1,salaried,urban,512,6
2026-10-15,7362,0,39000,240,1,1,salaried,semiurban,850,0
2026-10-12,4461,0,126000,180,1,0,salaried,urban,744,0
2026-10-05,2585,3393,137000,300,1,0,self_employed,urban,805,1
2026-10-05,2990,0,142000,360,1,0,self_employed,semiurban,718,0
2026-10-14,9454,0,123000,240,0,0,salaried,urban,571,1
2026-10-15,4279,793,113000,360,1,0,salaried,rural,739,0
2026-10-02,5242,978,93000,360,1,0,salaried,semiurban,776,0
2026-10-07,9957,3201,181000,360,1,2,salaried,urban,721,0
2026-10-12,3991,3277,94000,300,1,1,salaried,rural,685,1
2026-10-09,5496,0,61000,180,1,0,salaried,urban,760,0
2026-10-01,5085,0,86000,120,1,0,salaried,semiurban,758,0
2026-10-07,7287,0,193000,360,1,0,self_employed,semiurban,799,1
2026-10-02,5346,2041,92000,360,0,1,salaried,semiurban,500,6
2026-10-07,6617,0,155000,360,1,0,self_employed,semiurban,817,0
2026-10-12,8181,1999,63000,360,0,1,salaried,semiurban,532,6
2026-10-08,8212,1425,91000,360,1,1,self_employed,urban,798,1
2026-10-13,4524,538,62000,240,1,0,self_employed,semiurban,653,0
2026-10-12,5887,1283,189000,360,1,2,salaried,urban,732,0
2026-10-02,8173,0,226000,360,1,2,salaried,rural,762,0
2026-10-14,4882,6845,283000,180,1,0,salaried,urban,719,0
2026-10-13,6727,13032,58000,240,1,0,salaried,semiurban,700,0
2026-10-14,4831,2651,213000,360,1,0,self_employed,semiurban,703,0
2026-10-16,7137,0,92000,360,0,2,salaried,urban,534,1
2026-10-14,5136,0,52000,180,0,0,salaried,rural,586,6
2026-10-07,2576,2650,94000,360,0,0,salaried,urban,534,6
2026-10-16,3854,770,111000,240,0,2,salaried,urban,487,4
2026-10-07,2115,622,95000,360,1,3,self_employed,rural,727,1
2026-10-16,11332,0,48000,360,1,0,salaried,rural,707,0
2026-10-16,4257,3135,67000,360,1,0,self_employed,semiurban,790,0
2026-10-05,4558,6344,143000,360,1,1,salaried,urban,715,0
2026-10-09,7143,0,89000,180,1,1,unemployed,rural,661,0
2026-10-16,12031,2137,68000,300,1,0,self_employed,urban,706,1
2026-10-01,4680,4243,184000,360,0,0,self_employed,rural,555,0
2026-10-01,10716,858,38000,360,1,0,self_employed,urban,778,0
2026-10-05,2843,0,70000,240,1,0,salaried,urban,736,0
2026-10-05,5261,2213,177000,240,0,1,self_employed,semiurban,502,6
2026-10-07,3282,0,71000,360,1,0,self_employed,urban,600,0
2026-10-06,5069,2567,168000,360,0,1,salaried,urban,672,5
"""

TEMPLATE = pd.DataFrame([
    {"application_date": "2026-10-01", "applicant_income": 5400, "coapplicant_income": 1800, "loan_amount": 145000,
     "loan_term_months": 360, "credit_history": 1, "dependents": 1,
     "employment_status": "salaried", "property_area": "urban",
     "credit_score": 745, "late_payments_12m": 0},
    {"application_date": "2026-10-02", "applicant_income": 3100, "coapplicant_income": 0, "loan_amount": 210000,
     "loan_term_months": 240, "credit_history": 0, "dependents": 3,
     "employment_status": "self_employed", "property_area": "rural",
     "credit_score": 590, "late_payments_12m": 3},
])


def render() -> None:
    c = ctx()

    ui.page_header(
        "Score a file",
        "Upload a day's intake and get every application scored, routed and checked "
        "against policy in one pass.",
        eyebrow="Decisioning",
    )

    _spec()
    uploaded = st.file_uploader(
        "Application file", type=["csv"], label_visibility="collapsed",
        help="CSV with one row per application and the ten columns listed above.",
    )

    if uploaded is None:
        ui.note(
            "Upload a CSV to begin, or download the template above to see the expected "
            "shape. Columns may appear in any order; extra columns are carried through to "
            "the output untouched.",
            title="Waiting on a file",
        )
        return

    if uploaded.size > MAX_UPLOAD_MB * 1024 * 1024:
        ui.note(f"The file is larger than {MAX_UPLOAD_MB} MB. Split it and upload in parts.",
                title="File too large", tone="stop")
        return
    try:
        raw = pd.read_csv(uploaded)
    except Exception as exc:
        ui.note(f"That file could not be read as CSV: {esc(str(exc))}", title="File not readable",
                tone="stop")
        return
    if len(raw) > MAX_ROWS:
        ui.note(f"The file has {len(raw):,} rows; the limit is {MAX_ROWS:,} per upload.",
                title="Too many rows", tone="stop")
        return

    raw = _clean(raw)

    missing = [col for col in REQUIRED if col not in raw.columns]
    if missing:
        ui.note(
            "The file is missing " + ", ".join(f"<code>{m}</code>" for m in missing) +
            ". Add the columns and upload again — the template above has the right headers.",
            title="Columns missing", tone="stop",
        )
        return

    # Row-by-row validation: nothing is guessed. Bad rows are listed with the reason and left
    # out of the scoring; good rows are scored.
    valid, issues = validate_applications(raw)
    if not issues.empty:
        n_bad = issues["file_row"].nunique()
        ui.note(f"<b>{n_bad:,}</b> of {len(raw):,} rows have a problem and were <b>not scored</b>. "
                "Fix them in the source file and upload again; the list below says exactly what is wrong.",
                title="Rows rejected", tone="stop" if valid.empty else "warn")
        ui.table(issues.head(500), hide_index=True, height=min(300, 60 + 35 * min(len(issues), 8)))
        st.download_button("Download the problem list (CSV)", to_safe_csv(issues),
                           file_name="rows_not_scored.csv", mime="text/csv")
    if valid.empty:
        return

    _score(c, valid, filename=uploaded.name, n_rejected=int(issues["file_row"].nunique()) if not issues.empty else 0)


# -----------------------------------------------------------------------------------------
def _clean(raw: pd.DataFrame) -> pd.DataFrame:
    """Tolerate the usual spreadsheet damage: header case/spacing and text casing."""
    raw = raw.copy()
    raw.columns = (
        raw.columns.astype(str).str.replace("\ufeff", "", regex=False)
        .str.strip().str.lower().str.replace(r"[\s\-]+", "_", regex=True)
    )
    for col in ("employment_status", "property_area"):
        if col in raw.columns:
            raw[col] = (raw[col].astype("string").str.strip().str.lower()
                        .str.replace(r"[\s\-]+", "_", regex=True))
    return raw


# -----------------------------------------------------------------------------------------
def _template_bytes() -> tuple[bytes, str, int]:
    """Bytes, download name and row count for the template button."""
    try:
        if SAMPLE_PATH.exists():
            data = SAMPLE_PATH.read_bytes()
            rows = max(data.decode("utf-8-sig").strip().count("\n"), 0)
            return data, SAMPLE_PATH.name, rows
    except OSError:
        pass
    data = SAMPLE_CSV.encode("utf-8")
    return data, "application_sample_100.csv", SAMPLE_CSV.strip().count("\n")


def _spec() -> None:
    a, b = st.columns([1.7, 1], gap="large")
    with a:
        ui.section("What the file needs")
        spec = pd.DataFrame([
            ("applicant_income", "number", "Gross monthly income"),
            ("coapplicant_income", "number", "0 if there is no co-applicant"),
            ("loan_amount", "number", "Requested principal"),
            ("loan_term_months", "number", "12 to 480"),
            ("credit_history", "0 or 1", "1 = history on file"),
            ("dependents", "number", "0 to 10"),
            ("employment_status", "text", "salaried, self_employed or unemployed"),
            ("property_area", "text", "urban, semiurban or rural"),
            ("credit_score", "number", "300 to 850"),
            ("late_payments_12m", "number", "Late payments in the last 12 months, 0 to 24"),
            ("application_date", "date (optional)", "YYYY-MM-DD or DD/MM/YYYY, day received. Leave the column out to use "
                                                    "today; not in the future"),
        ], columns=["Column", "Type", "Notes"])
        ui.table(spec, hide_index=True)
    with b:
        ui.section("Template")
        data, fname, rows = _template_bytes()
        st.markdown(
            f'<p class="cd-lede" style="font-size:0.87rem;">{rows} example rows with the '
            f'exact headers the scorer expects.</p>', unsafe_allow_html=True,
        )
        st.download_button(
            "Download template (CSV)", data, file_name=fname, mime="text/csv",
        )


# -----------------------------------------------------------------------------------------
def _by_date(scored: pd.DataFrame, order: list, colors: dict) -> None:
    """When a file spans several received dates: routing per day and how long rows have waited."""
    if "application_date" not in scored.columns:
        return
    d = pd.to_datetime(scored["application_date"], errors="coerce")
    scored["days_waiting"] = (today_local() - d.dt.normalize()).dt.days
    if d.dt.normalize().nunique() < 2:
        return
    ui.section("By day received",
               "Routing for each day in the file, and how long the oldest applications have been waiting.")
    t = (scored.assign(day=d.dt.strftime("%d/%m"), sortkey=d.dt.normalize())
         .groupby(["sortkey", "day", "routing"], observed=True).size().reset_index(name="n").sort_values("sortkey"))
    fig = go.Figure()
    for band in order:
        sub = t[t["routing"] == band]
        if len(sub):
            fig.add_bar(x=sub["day"], y=sub["n"], name=band, marker_color=colors[band])
    fig.update_layout(barmode="stack", xaxis=dict(type="category", title="Received"),
                      yaxis=dict(title="Applications"), legend=dict(orientation="h", y=1.15, x=0))
    ui.chart(fig, height=260)
    old = scored[scored["days_waiting"] > SLA_DAYS]
    if len(old):
        ui.note(f"<b>{len(old):,}</b> application(s) were received more than {SLA_DAYS} days ago "
                f"(oldest: {int(scored['days_waiting'].max())} days). Prioritise them.",
                title="Waiting too long", tone="warn")


# -----------------------------------------------------------------------------------------
def _score(c, raw: pd.DataFrame, filename: str, n_rejected: int = 0) -> None:
    cutoff = c.cutoff

    # Same scoring + hard policy + routing functions as the single-application page.
    scored = dec.score_frame(c.model.pipeline, raw, threshold=cutoff, policy=c.policy, cutoff=cutoff)

    from src import risk_economics as econ
    scored["suggested_rate"] = [econ.suggested_rate(r, c.settings) for r in scored["routing"]]
    if "loan_amount" in scored.columns:
        coll = scored["collateral_value"] if "collateral_value" in scored.columns else pd.Series(0.0, index=scored.index)
        scored["expected_loss"] = [
            econ.expected_loss(float(a), float(cv or 0), r, c.settings)["el"]
            for a, cv, r in zip(scored["loan_amount"], coll.fillna(0), scored["routing"])]

    user = auth.current_user()
    audit.log_if_changed(
        "batch_file", user.username, user.role, "score_file",
        f"{filename} - {len(scored):,} scored, {n_rejected:,} rejected - policy v{c.policy_version} - "
        f"model {c.model_version} - cut-off {cutoff:.0%}",
    )

    oor = scored["range_warning"].ne("")
    if oor.any():
        ui.note(f"<b>{int(oor.sum()):,}</b> application(s) fall outside the range of data the model was "
                "trained on. They are capped at Refer and marked in the results.",
                title="Outside the model's experience", tone="warn")

    ui.section(f"{len(scored):,} applications scored",
               f"Policy v{c.policy_version}, cut-off {cutoff:.0%}, hard rules applied before routing.")

    counts = scored["routing"].value_counts()
    order = ["Fast-track", "Review", "Refer", "Decline"]
    colors = {"Fast-track": ui.LOW, "Review": "#5E9E7E", "Refer": ui.MED, "Decline": ui.HIGH}

    cols = st.columns(4, gap="small")
    for col, band in zip(cols, order):
        n = int(counts.get(band, 0))
        with col:
            ui.kpi(band, f"{n:,}",
                   foot=f"{n / len(scored) * 100:.0f}% of the file" if len(scored) else None)

    _by_date(scored, order, colors)

    st.markdown("")
    left, right = st.columns([1.25, 1], gap="large")

    with left:
        ui.section("Score distribution")
        fig = go.Figure()
        for band in order:
            sub = scored[scored["routing"] == band]
            if sub.empty:
                continue
            fig.add_histogram(
                x=sub["approval_probability"] * 100, nbinsx=30, name=band,
                marker_color=colors[band], marker_line_width=0, opacity=0.85,
                hovertemplate=f"{band}<br>%{{y}} applications<extra></extra>",
            )
        fig.add_vline(x=cutoff * 100, line_color=ui.INK, line_width=1.4, line_dash="dot",
                      annotation_text=f"cut-off {cutoff:.0%}",
                      annotation_font=dict(size=11, color=ui.INK))
        fig.update_layout(barmode="stack",
                          xaxis=dict(title="Approval probability", ticksuffix="%"),
                          yaxis=dict(title="Applications"))
        ui.chart(fig, height=320)

    with right:
        ui.section("Policy breaches in this file")
        blocked = scored[~scored["policy_pass"]]
        if blocked.empty:
            ui.note("No application in this file breaches policy.", title="All clear")
        else:
            reasons = blocked["breach_reason"].str.split(", ").explode().value_counts()
            fig = go.Figure(go.Bar(
                y=list(reasons.index), x=list(reasons.values), orientation="h",
                marker_color=ui.MED, marker_line_width=0, opacity=0.9,
                text=[f"{v:,}" for v in reasons.values], textposition="outside",
                textfont=dict(size=11.5, color=ui.INK),
            ))
            fig.update_layout(
                xaxis=dict(title="Applications", range=[0, reasons.max() * 1.25]),
                yaxis=dict(title="", autorange="reversed"), bargap=0.4,
            )
            ui.chart(fig, height=max(200, 56 * len(reasons)))
            st.caption(
                f"{len(blocked):,} of {len(scored):,} applications are blocked by policy "
                "regardless of score, and have been routed to decline."
            )

    _results_table(scored)


def _results_table(scored: pd.DataFrame) -> None:
    ui.section("Results")

    show_only = ui.choice(
        "Show", ["All", "Fast-track", "Review", "Refer", "Decline", "Policy breaches"],
        default="All", key="batch_filter")

    if show_only == "Policy breaches":
        subset = scored[~scored["policy_pass"]]
    elif show_only != "All":
        subset = scored[scored["routing"] == show_only]
    else:
        subset = scored

    display = pd.DataFrame({
        "Score": subset["approval_probability"] * 100,
        "Routing": subset["routing"].astype(str),
        "Loan": subset["loan_amount"],
        "Monthly income": subset["total_income"],
        "DTI": subset["debt_to_income_ratio"] * 100,
        "Credit history": subset["credit_history"].map({1: "On file", 0: "None"}),
        "Employment": subset["employment_status"].astype(str).str.replace("_", "-"),
        "Area": subset["property_area"].astype(str).str.title(),
        "Policy": subset["policy_pass"].map({True: "Pass", False: "Breach"}),
        "Why it is flagged": subset["breach_reason"],
        "Model range": subset["range_warning"].replace("", "OK"),
    })

    ui.table(
        ui.gradient(display.style.format({
            "Score": "{:.1f}%", "Loan": "${:,.0f}",
            "Monthly income": "${:,.0f}", "DTI": "{:.0f}%",
        }), cmap="BuGn", subset=["Score"], vmin=0, vmax=100), hide_index=True, height=420,
    )

    export = scored.drop(columns=["breach_count"], errors="ignore")
    st.download_button(
        "Download scored file (CSV)", to_safe_csv(export),
        file_name="scored_applications.csv", mime="text/csv", type="primary",
    )
    ui.disclaimer(compact=True)