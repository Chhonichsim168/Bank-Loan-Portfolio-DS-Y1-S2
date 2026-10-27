"""
generate_report.py
===================
Generates a fully self-contained, static HTML analytics report
(reports/Bank_Loan_Portfolio_Analytics_Report.html) with every required
chart, table, interpretation, finding, and recommendation embedded as
base64 images — no server required. Useful for presentations, emailing to
stakeholders, or archiving alongside a specific data snapshot.

Usage:
    python generate_report.py
"""

from __future__ import annotations

import base64
import io
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from src.data_pipeline import run_pipeline
from src import analytics as an
from src import visualizations as viz
from src.risk_model import train_model

ROOT = Path(__file__).resolve().parent
OUT_HTML = ROOT / "reports" / "Bank_Loan_Portfolio_Analytics_Report.html"


def fig_to_base64(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=140, bbox_inches="tight")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def df_to_html(df: pd.DataFrame, **kwargs) -> str:
    return df.to_html(classes="tbl", border=0, **kwargs)


def build_report() -> str:
    df, report = run_pipeline(str(ROOT / "data" / "loan_data.csv"))
    model = train_model(df)

    charts = {
        "Approval Rate by Employment Status": viz.chart_approval_rate_by_employment(df),
        "Approval Rate Across Income Deciles": viz.chart_approval_rate_by_income_decile(df),
        "Distribution of Total Household Income": viz.chart_income_distribution(df),
        "Portfolio Share by Risk Level": viz.chart_risk_level_share(df),
        "Loan Amount vs. Income (by Outcome)": viz.chart_income_vs_loan_scatter(df),
        "Debt-to-Income by Approval Outcome": viz.chart_dti_boxplot_by_approval(df),
        "Correlation Matrix": viz.chart_correlation_heatmap(df),
        "Approval/Rejection by Property Area": viz.chart_property_area_outcomes(df),
    }
    chart_b64 = {title: fig_to_base64(fig) for title, fig in charts.items()}

    interpretations = {
        "Approval Rate by Employment Status": "Salaried applicants show the highest approval rate, "
            "followed by self-employed, with unemployed applicants approved far less often — "
            "employment stability is a visible factor in underwriting outcomes.",
        "Approval Rate Across Income Deciles": "Approval rate increases fairly steadily from the "
            "lowest to the highest income decile, though the relationship flattens at the top, "
            "suggesting income alone stops being the binding constraint for high earners.",
        "Distribution of Total Household Income": "Household income is right-skewed: most applicants "
            "cluster in the lower-middle range, with a long tail of high-income households pulling the "
            "mean above the median.",
        "Portfolio Share by Risk Level": "The majority of the portfolio is Low or Medium risk; the "
            "High-risk segment is a small but important minority requiring closer monitoring.",
        "Loan Amount vs. Income (by Outcome)": "Rejections (red) concentrate where loan amount is high "
            "relative to income, visually confirming that affordability — not just loan size or income "
            "alone — drives outcomes.",
        "Debt-to-Income by Approval Outcome": "Approved applicants have a visibly lower and tighter "
            "debt-to-income distribution than rejected applicants, whose distribution stretches into "
            "much higher, riskier ratios.",
        "Correlation Matrix": "Debt-to-income ratio and credit history show the strongest (negative and "
            "positive, respectively) correlation with approval — stronger than income or loan amount alone.",
        "Approval/Rejection by Property Area": "Urban and semiurban properties show a healthier approval "
            "mix than rural properties, consistent with the pivot-table analysis elsewhere in this report.",
    }

    q1 = an.answer_q1_credit_history_effect(df)
    q2 = an.answer_q2_income_vs_approval(df)
    q3 = an.answer_q3_area_employment_patterns(df)
    q4 = an.answer_q4_risk_segment_sizes(df)
    q5 = an.answer_q5_dti_threshold_effect(df)
    stats_df = an.numeric_summary_stats(df, [
        "applicant_income", "coapplicant_income", "loan_amount", "total_income",
        "loan_to_income_ratio", "estimated_emi", "debt_to_income_ratio"])

    dd = pd.DataFrame([
        ("applicant_income", "float", "Primary applicant's monthly income (USD)", "5324.99"),
        ("coapplicant_income", "float", "Co-applicant's monthly income (USD), 0 if none", "1429.28"),
        ("loan_amount", "float", "Requested loan principal (USD)", "134000.00"),
        ("loan_term_months", "int", "Requested loan repayment term, in months", "360"),
        ("credit_history", "int (0/1)", "1 = good credit history on file, 0 = poor/none", "1"),
        ("credit_score", "int", "Credit score, 300 to 850", "712"),
        ("late_payments_12m", "int", "Late payments in the last 12 months", "0"),
        ("dependents", "int", "Number of financial dependents", "2"),
        ("employment_status", "categorical", "salaried / self_employed / unemployed", "salaried"),
        ("property_area", "categorical", "urban / semiurban / rural", "urban"),
        ("approved", "int (0/1)", "Target: 1 = approved, 0 = rejected", "1"),
        ("total_income", "float (derived)", "applicant_income + coapplicant_income", "6754.27"),
        ("loan_to_income_ratio", "float (derived)", "loan_amount / monthly total_income", "19.85"),
        ("loan_to_annual_income", "float (derived)", "loan_amount / (total_income x 12)", "1.65"),
        ("estimated_emi", "float (derived)", "Amortized monthly installment @ 8.5% p.a.", "1030.42"),
        ("debt_to_income_ratio", "float (derived)", "estimated_emi / total_income", "0.15"),
        ("income_bracket", "categorical (derived)", "Low/Medium/High tertile of total_income", "Medium"),
        ("loan_size_category", "categorical (derived)", "Small/Medium/Large/Jumbo bin", "Medium"),
        ("household_size", "int (derived)", "dependents + applicant (+ co-applicant)", "3"),
        ("risk_level", "categorical (derived)", "Low/Medium/High additive score (credit history, credit score, late payments, DTI, employment, loan-to-income)", "Low"),
    ], columns=["Field", "Type", "Description", "Example"])

    findings = [
        f"Credit history is the strongest single driver of approval: good-history applicants are "
        f"approved {q1.loc[1,'approval_rate_pct']:.1f}% of the time vs. {q1.loc[0,'approval_rate_pct']:.1f}% "
        "for poor/no-history applicants.",
        "Debt-to-income ratio — not raw income — is the key affordability signal; approval collapses "
        "once DTI exceeds roughly 30-40%.",
        f"The portfolio is concentrated in lower risk: {(df['risk_level']=='Low').mean()*100:.1f}% Low-risk vs. "
        f"{(df['risk_level']=='High').mean()*100:.1f}% High-risk.",
        "Self-employed applicants and rural properties consistently underperform salaried/urban "
        "segments in approval rate, even controlling for income.",
        f"A simple 8-feature logistic regression model reaches {model.roc_auc:.2f} ROC AUC, showing "
        "application-form data alone carries strong predictive signal for triage purposes.",
    ]
    recommendations = [
        "Weight credit history heavily in pre-screening, with a manual review path for good-income/"
        "low-DTI applicants who lack strong credit history.",
        "Adopt an explicit debt-to-income cap (~40-45%) as underwriting policy.",
        "Audit the self-employed / rural approval gap for process friction vs. genuine risk difference.",
        "Introduce risk-based pricing for the High-risk segment instead of blanket rejection.",
        "Use the predictive model only as a triage aid, monitored quarterly for drift and fairness.",
        "Enrich the dataset with the full bureau report (tradelines, balances, late-payment severity), existing liabilities, and collateral data to improve "
        "model accuracy over time.",
    ]

    css = """
    body{font-family:'Source Sans Pro',Arial,sans-serif;color:#1B1F23;background:#F5F6F8;margin:0;}
    .wrap{max-width:1100px;margin:0 auto;padding:2.5rem 2rem 5rem;}
    h1{font-family:Georgia,serif;color:#0B2545;border-bottom:4px solid #C89B3C;padding-bottom:.5rem;}
    h2{font-family:Georgia,serif;color:#0B2545;margin-top:2.6rem;border-left:5px solid #C89B3C;padding-left:.6rem;}
    h3{color:#13315C;}
    .meta{color:#3E5C76;font-size:.95rem;margin-bottom:2rem;}
    .kpis{display:flex;gap:1rem;flex-wrap:wrap;margin:1.2rem 0 2rem;}
    .kpi{background:white;border:1px solid #E1E4E9;border-left:4px solid #C89B3C;border-radius:6px;
         padding:.9rem 1.2rem;min-width:150px;box-shadow:0 1px 2px rgba(0,0,0,.04);}
    .kpi .lbl{color:#3E5C76;font-size:.8rem;font-weight:600;text-transform:uppercase;letter-spacing:.02em;}
    .kpi .val{font-size:1.6rem;font-weight:700;color:#0B2545;}
    .chart{background:white;border:1px solid #E1E4E9;border-radius:8px;padding:1.2rem;margin:1.2rem 0;}
    .chart img{max-width:100%;}
    .note{background:#EEF2F7;border-left:4px solid #0B2545;padding:.7rem 1rem;border-radius:4px;margin-top:.7rem;font-size:.93rem;}
    table.tbl{border-collapse:collapse;width:100%;margin:.8rem 0 1.2rem;font-size:.9rem;}
    table.tbl th{background:#0B2545;color:white;padding:.5rem .7rem;text-align:left;}
    table.tbl td{padding:.45rem .7rem;border-bottom:1px solid #E1E4E9;}
    table.tbl tr:nth-child(even){background:#F5F6F8;}
    ol li, ul li{margin-bottom:.5rem;line-height:1.5;}
    .badge{display:inline-block;background:#C89B3C;color:#0B2545;font-weight:700;border-radius:3px;
           padding:.15rem .6rem;font-size:.75rem;letter-spacing:.03em;margin-bottom:.6rem;}
    .disclaimer{background:#FBEBBD;border:1px solid #C89B3C;padding:1rem 1.2rem;border-radius:6px;margin:1rem 0;}
    """

    def chart_block(title):
        return f"""
        <div class="chart">
          <h3>{title}</h3>
          <img src="data:image/png;base64,{chart_b64[title]}"/>
          <div class="note">{interpretations[title]}</div>
        </div>"""

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>Bank Loan Portfolio Analytics — Report</title>
<style>{css}</style></head><body><div class="wrap">

<span class="badge">ANALYTICS REPORT</span>
<h1>Bank Loan Portfolio Analytics</h1>
<div class="meta">Generated from {report.rows_out:,} clean loan applications ·
Data pipeline: {report.rows_in:,} raw → {report.rows_out:,} clean rows,
{report.duplicates_dropped} duplicates removed, {report.invalid_rows_dropped} invalid rows removed.</div>

<div class="kpis">
  <div class="kpi"><div class="lbl">Applications</div><div class="val">{len(df):,}</div></div>
  <div class="kpi"><div class="lbl">Approval Rate</div><div class="val">{df['approved'].mean()*100:.1f}%</div></div>
  <div class="kpi"><div class="lbl">Avg Loan Amount</div><div class="val">${df['loan_amount'].mean():,.0f}</div></div>
  <div class="kpi"><div class="lbl">Avg Household Income</div><div class="val">${df['total_income'].mean():,.0f}</div></div>
  <div class="kpi"><div class="lbl">Model ROC AUC</div><div class="val">{model.roc_auc:.3f}</div></div>
</div>

<h2>1. Business Problem &amp; Project Scope</h2>
<p>Retail lending teams review thousands of loan applications without a systematic, data-driven view
of what drives approval, how risk concentrates across the portfolio, or where underwriting policy could
be sharpened. This project analyzes a portfolio of {len(df):,} historical loan applications to surface
approval drivers, quantify risk concentration, and provide a transparent decision-support system for
loan officers and risk management.</p>
<p><b>In scope:</b> applicant/co-applicant income, loan amount &amp; term, credit history, employment
status, property area, dependents, credit score, 12-month late payments, and approval outcome.
<b>Out of scope:</b> the full bureau report (tradelines, balances, inquiries), collateral valuation, other liabilities, macroeconomic conditions, and fraud signals.</p>

<h2>2. Objectives</h2>
<ol>
<li>Quantify the key drivers of loan approval with statistical evidence.</li>
<li>Segment the loan portfolio into actionable risk tiers and measure each tier's size and performance.</li>
<li>Build and evaluate a transparent predictive model estimating approval probability, targeting ROC AUC ≥ 0.80.</li>
</ol>

<h2>3. Analytical Questions</h2>
<ol>
<li>How strongly does credit history influence loan approval?</li>
<li>Does higher applicant income correlate with higher approval likelihood?</li>
<li>Do approval patterns differ across property area and employment type?</li>
<li>What share of the portfolio falls into each risk segment, and how do they perform?</li>
<li>At what debt-to-income ratio does approval likelihood drop off sharply?</li>
</ol>

<h2>4. Data Dictionary</h2>
{df_to_html(dd, index=False)}

<h2>5. Data Quality Pipeline</h2>
<pre style="background:#0B2545;color:#E7EAF0;padding:1rem;border-radius:6px;overflow-x:auto;">{report.summary()}</pre>

<h2>6. Statistical Summary</h2>
{df_to_html(stats_df)}
<div class="note">Median total income sits below the mean, confirming the right-skew visible in the
income histogram below — a small share of high earners pulls the average upward.</div>

<h2>7. Visual Analysis</h2>
{''.join(chart_block(t) for t in charts)}

<h2>8. Answers to the Analytical Questions</h2>
<h3>Q1 — Credit History Effect</h3>{df_to_html(q1)}
<h3>Q2 — Income Bracket Effect</h3>{df_to_html(q2)}
<h3>Q3 — Area × Employment Pivot (Approval Rate %)</h3>{df_to_html(q3)}
<h3>Q4 — Risk Segment Sizes &amp; Performance</h3>{df_to_html(q4)}
<h3>Q5 — Debt-to-Income Threshold Effect</h3>{df_to_html(q5)}

<h2>9. Predictive Model Performance</h2>
<div class="kpis">
  <div class="kpi"><div class="lbl">Accuracy</div><div class="val">{model.accuracy*100:.1f}%</div></div>
  <div class="kpi"><div class="lbl">Precision</div><div class="val">{model.precision*100:.1f}%</div></div>
  <div class="kpi"><div class="lbl">Recall</div><div class="val">{model.recall*100:.1f}%</div></div>
  <div class="kpi"><div class="lbl">F1</div><div class="val">{model.f1*100:.1f}%</div></div>
  <div class="kpi"><div class="lbl">ROC AUC</div><div class="val">{model.roc_auc:.3f}</div></div>
</div>
<div class="disclaimer"><b>Disclaimer:</b> Illustrative decision-support model only — not a
production underwriting system. Must not be used as the sole basis for real credit decisions.</div>

<h2>10. Key Findings</h2>
<ol>{''.join(f"<li>{f}</li>" for f in findings)}</ol>

<h2>11. Recommendations</h2>
<ol>{''.join(f"<li>{r}</li>" for r in recommendations)}</ol>

<h2>12. About This System</h2>
<p>Built with Python, Pandas, NumPy, scikit-learn, Matplotlib/Seaborn, Plotly, and Streamlit.
See the accompanying GitHub repository for full source code, the interactive dashboard
(<code>app.py</code>), and setup instructions (<code>README.md</code>).</p>

</div></body></html>"""
    return html


if __name__ == "__main__":
    OUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    html = build_report()
    OUT_HTML.write_text(html, encoding="utf-8")
    print(f"Report written to: {OUT_HTML}")
