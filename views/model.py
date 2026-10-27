"""Model performance — validation evidence, written for a model risk reviewer."""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src import decisioning as dec
from src import ui
from src.state import ctx, fingerprint_of, honest_probabilities


def render() -> None:
    c = ctx()
    m = c.model

    ui.page_header(
        "Model performance",
        "Discrimination, calibration and stability for the approval model, and how it "
        "behaves across segments.",
        eyebrow="Governance",
    )

    _headline(m)
    _evidence(c)
    ui.disclaimer()

    tabs = ["Discrimination", "Calibration", "What the model weighs", "Performance by segment", "Challenger"]
    if c.has_dates:
        tabs.insert(2, "Stability over time")
    tab_list = st.tabs(tabs)
    tab_disc, tab_cal = tab_list[0], tab_list[1]
    tab_coef, tab_fair, tab_chal = tab_list[-3], tab_list[-2], tab_list[-1]
    if c.has_dates:
        with tab_list[2]:
            _over_time(c)
    with tab_disc:
        _discrimination(m)
    with tab_cal:
        _calibration(c)
    with tab_coef:
        _coefficients(m)
    with tab_fair:
        _by_segment(c)
    with tab_chal:
        _challenger(c)


# -----------------------------------------------------------------------------------------
def performance_by_period(book: pd.DataFrame, proba: np.ndarray, period_col: str = "application_quarter") -> pd.DataFrame:
    """Out-of-fold AUC, average score and actual approval rate for each period. A falling AUC or a
    widening gap between score and actual rate is the signal to retrain."""
    from sklearn.metrics import roc_auc_score
    t = pd.DataFrame({"period": book[period_col].values, "y": book["approved"].values, "p": proba})
    rows = []
    for per, g in t.groupby("period"):
        auc = roc_auc_score(g["y"], g["p"]) if g["y"].nunique() == 2 and len(g) >= 30 else np.nan
        rows.append({"period": per, "applications": len(g), "auc": auc,
                     "avg_score": g["p"].mean(), "actual_rate": g["y"].mean()})
    out = pd.DataFrame(rows).sort_values("period").reset_index(drop=True)
    out["gap"] = out["avg_score"] - out["actual_rate"]
    return out


def _over_time(c) -> None:
    ui.section("Stability over time",
               "Every application scored by a model that never saw it (out-of-fold), grouped by the quarter it "
               "was received. Ranking quality should hold steady and the average score should track the actual "
               "approval rate. A drop in the newest quarters means the model is ageing.")
    proba = honest_probabilities(c.book, fingerprint_of(c.book))
    t = performance_by_period(c.book, proba)
    fig = go.Figure()
    fig.add_scatter(x=t["period"], y=t["auc"], name="AUC (ranking)", mode="lines+markers",
                    line=dict(color=ui.BRAND_DEEP, width=2.5), hovertemplate="%{x}<br>AUC %{y:.3f}<extra></extra>")
    fig.add_scatter(x=t["period"], y=t["avg_score"], name="Average score", mode="lines",
                    line=dict(color=ui.MED, width=2, dash="dot"), hovertemplate="%{x}<br>score %{y:.1%}<extra></extra>")
    fig.add_scatter(x=t["period"], y=t["actual_rate"], name="Actual approval rate", mode="lines",
                    line=dict(color=ui.INK_SOFT, width=2), hovertemplate="%{x}<br>actual %{y:.1%}<extra></extra>")
    fig.add_hline(y=0.7, line_dash="dash", line_color=ui.HIGH, line_width=1,
                  annotation_text="AUC 0.70 - review", annotation_font=dict(size=10, color=ui.HIGH))
    fig.update_layout(yaxis=dict(range=[0, 1], tickformat=".2f"), xaxis=dict(type="category"),
                      legend=dict(orientation="h", y=1.12, x=0))
    ui.chart(fig, height=320)
    worst = t.dropna(subset=["auc"])
    if len(worst):
        w = worst.loc[worst["auc"].idxmin()]
        st.caption(f"Weakest quarter: {w['period']} (AUC {w['auc']:.3f}, {int(w['applications'])} applications). "
                   f"Largest score gap: {t.loc[t['gap'].abs().idxmax(), 'period']} "
                   f"({t['gap'].abs().max() * 100:.1f} pp).")
    ui.table(t.rename(columns={"period": "Quarter", "applications": "Applications", "auc": "AUC",
                               "avg_score": "Average score", "actual_rate": "Actual rate", "gap": "Score - actual"})
             .style.format({"AUC": "{:.3f}", "Average score": "{:.1%}", "Actual rate": "{:.1%}",
                            "Score - actual": "{:+.1%}"}, na_rep="-"), hide_index=True)


# -----------------------------------------------------------------------------------------
def _evidence(c) -> None:
    """Calibration, stability over folds / time, version, and the limits of what was validated."""
    m = c.model
    cols = st.columns(5, gap="small")
    with cols[0]:
        ui.kpi("Calibration error (ECE)", f"{m.ece:.3f}",
               foot="average gap between score and actual approval rate; under 0.03 is good")
    with cols[1]:
        ui.kpi("Brier score", f"{m.brier:.3f}", foot="squared score error, out-of-fold; lower is better")
    with cols[2]:
        ui.kpi("AUC over 5 folds", f"{m.cv_auc_mean:.3f}", foot=f"+/- {m.cv_auc_std:.3f} between folds")
    with cols[3]:
        ui.kpi("Out-of-time AUC", "n/a" if m.oot_auc is None else f"{m.oot_auc:.3f}",
               foot="needs a dated extract" if m.oot_auc is None else "newest 25% held out")
    with cols[4]:
        ui.kpi("Model version", m.model_version, foot=f"{m.train_rows:,} rows - policy v{c.policy_version}")
    ui.note(m.oot_note + (f" {m.excluded_rows:,} row(s) with an imputed credit score, late-payment count or "
                          "credit-history flag were excluded from training." if m.excluded_rows else "")
            + " The target is the bank's <b>past approval decisions</b>, not repayment: the model "
            "reproduces earlier judgement, including its biases, until it is retrained on observed "
            "default or delinquency outcomes.", title="What this validation does not show",
            tone="warn" if m.oot_auc is None else "info")


def _headline(m) -> None:
    cols = st.columns(5, gap="small")
    targets = {"roc": 0.80}

    with cols[0]:
        ui.kpi("ROC AUC", f"{m.roc_auc:.3f}",
               delta=f"{m.roc_auc - targets['roc']:+.3f} vs target",
               delta_dir=ui.delta_dir(m.roc_auc - targets["roc"]),
               foot="ranking quality; 0.5 is a coin flip")
    with cols[1]:
        ui.kpi("Accuracy", ui.pct(m.accuracy), foot="at the 0.50 cut-off")
    with cols[2]:
        ui.kpi("Precision", ui.pct(m.precision), foot="of those approved, share truly good")
    with cols[3]:
        ui.kpi("Recall", ui.pct(m.recall), foot="of good applications, share caught")
    with cols[4]:
        ui.kpi("F1", ui.pct(m.f1), foot="balance of the two above")


# -----------------------------------------------------------------------------------------
def _discrimination(m) -> None:
    left, right = st.columns(2, gap="large")

    with left:
        ui.section("ROC curve")
        fig = go.Figure()
        fig.add_scatter(x=m.fpr, y=m.tpr, mode="lines", name="Model",
                        line=dict(color=ui.BRAND, width=2.6),
                        fill="tozeroy", fillcolor="rgba(11,107,98,0.08)",
                        hovertemplate="FPR %{x:.2f}<br>TPR %{y:.2f}<extra></extra>")
        fig.add_scatter(x=[0, 1], y=[0, 1], mode="lines", name="No skill",
                        line=dict(color=ui.BORDER_STRONG, width=1.4, dash="dash"),
                        hoverinfo="skip")
        fig.update_layout(
            xaxis=dict(title="False positive rate", range=[0, 1]),
            yaxis=dict(title="True positive rate", range=[0, 1.02]),
            legend=dict(orientation="h", y=1.08, x=0),
        )
        ui.chart(fig, height=340)
        ui.note(
            f"An AUC of <b>{m.roc_auc:.3f}</b> means that for a randomly drawn pair — one "
            f"application the bank approved, one it declined — the model scores the approved "
            f"one higher about {m.roc_auc * 100:.0f}% of the time. That is strong for ten "
            "application fields and no full bureau report, and it is also the ceiling of what "
            "those fields can tell you."
        )

    with right:
        ui.section("Confusion matrix", "On the held-out test set, at the 0.50 cut-off.")
        cm = m.confusion
        labels = [["True decline", "False approve"], ["Missed good", "True approve"]]
        fig = go.Figure(go.Heatmap(
            z=cm, x=["Model: decline", "Model: approve"],
            y=["Bank declined", "Bank approved"],
            colorscale=[[0, "#F7F9FB"], [1, ui.BRAND]],
            text=[[f"{labels[i][j]}<br><b>{cm[i][j]:,}</b>" for j in range(2)] for i in range(2)],
            texttemplate="%{text}", textfont=dict(size=13, color=ui.INK),
            showscale=False, xgap=3, ygap=3,
            hovertemplate="%{y} · %{x}<br>%{z:,} applications<extra></extra>",
        ))
        fig.update_layout(xaxis=dict(title="", side="top"),
                          yaxis=dict(title="", autorange="reversed"))
        ui.chart(fig, height=280)
        fp, fn = int(cm[0][1]), int(cm[1][0])
        ui.note(
            f"The two error cells are not equivalent. <b>{fp}</b> false approvals are "
            f"applications the bank declined that the model would let through — potential "
            f"credit loss. <b>{fn}</b> missed good applications are lost margin. Which "
            "matters more is a business decision, and it is set on the Policy and cut-offs "
            "page, not here."
        )


# -----------------------------------------------------------------------------------------
def _calibration(c) -> None:
    ui.section(
        "Calibration",
        "Does a score of 70% actually mean 70% of those applications were approved? A model "
        "can rank well and still be badly calibrated, and a miscalibrated score cannot be "
        "used to set a cut-off.",
    )

    proba = honest_probabilities(c.book, fingerprint_of(c.book))
    y = c.book["approved"].values

    bins = np.linspace(0, 1, 11)
    idx = np.clip(np.digitize(proba, bins) - 1, 0, 9)
    frame = pd.DataFrame({"bin": idx, "proba": proba, "actual": y})
    g = frame.groupby("bin").agg(
        predicted=("proba", "mean"), observed=("actual", "mean"), n=("actual", "size")
    )
    g = g[g["n"] >= 15]

    left, right = st.columns([1.3, 1], gap="large")
    with left:
        fig = go.Figure()
        fig.add_scatter(x=[0, 1], y=[0, 1], mode="lines", name="Perfect calibration",
                        line=dict(color=ui.BORDER_STRONG, width=1.4, dash="dash"),
                        hoverinfo="skip")
        fig.add_scatter(
            x=g["predicted"], y=g["observed"], mode="lines+markers", name="This model",
            line=dict(color=ui.BRAND, width=2.4),
            marker=dict(size=g["n"] / g["n"].max() * 16 + 6, color=ui.BRAND),
            customdata=g["n"],
            hovertemplate="Predicted %{x:.0%}<br>Observed %{y:.0%}"
                          "<br>%{customdata:,} applications<extra></extra>",
        )
        fig.update_layout(
            xaxis=dict(title="Predicted approval probability", tickformat=".0%", range=[0, 1]),
            yaxis=dict(title="Observed approval rate", tickformat=".0%", range=[0, 1]),
            legend=dict(orientation="h", y=1.08, x=0),
        )
        ui.chart(fig, height=380)

    with right:
        gap = float((g["observed"] - g["predicted"]).abs().mean())
        ui.kpi("Mean calibration gap", f"{gap * 100:.1f}pp",
               delta="well calibrated" if gap < 0.05 else "check before use",
               delta_dir="up" if gap < 0.05 else "down",
               foot="average distance from the diagonal")
        st.markdown("")
        ui.note(
            "Marker size is the number of applications in each band. Points above the "
            "diagonal mean the model is under-confident in that range; points below mean it "
            "is over-confident. Bands with fewer than 15 applications are suppressed because "
            "their observed rate would be noise.",
            title="Reading this chart",
        )


# -----------------------------------------------------------------------------------------
def _coefficients(m) -> None:
    ui.section(
        "What the model weighs",
        "The score blends a sign-constrained logistic regression (75%) with a monotonic "
        "gradient-boosted model (25%). The weights below describe the logistic part only "
        "(a guide to direction and strength). The reasons shown for an individual application are "
        "computed on the final blended, calibrated score, so they always add up to it; the boosted "
        "part adds interactions such as a large loan on a weak credit file. Credit score and late payments are constrained to point "
        "the right way: a better score never lowers approval and a late payment never raises it.",
    )

    fi = m.feature_importance.head(12).copy()
    fi["label"] = fi["feature"].map(
        lambda f: dec.FEATURE_LABELS.get(f, f.replace("_", " ").capitalize())
    )
    fi = fi.sort_values("coefficient")

    fig = go.Figure(go.Bar(
        y=fi["label"], x=fi["coefficient"], orientation="h",
        marker_color=[ui.LOW if v >= 0 else ui.HIGH for v in fi["coefficient"]],
        marker_line_width=0, opacity=0.9,
        text=[f"{v:+.2f}" for v in fi["coefficient"]], textposition="outside",
        textfont=dict(size=11, color=ui.INK),
        hovertemplate="%{y}<br>%{x:+.3f} log-odds per standard deviation<extra></extra>",
    ))
    fig.add_vline(x=0, line_color=ui.BORDER_STRONG, line_width=1)
    span = float(fi["coefficient"].abs().max()) * 1.35
    fig.update_layout(
        xaxis=dict(title="Effect on approval log-odds", range=[-span, span], zeroline=False),
        yaxis=dict(title=""), bargap=0.32,
    )
    ui.chart(fig, height=max(340, 34 * len(fi)))

    ui.note(
        "Numeric features are standardised, so each weight reads as the effect of a one "
        "standard-deviation move in that field, holding the others fixed. Categorical "
        "weights read against the omitted baseline (salaried, rural). Weights are not "
        "reasons on their own — an applicant's reason codes combine these weights with "
        "their actual values, which is what the scoring page shows.",
        title="How to read a coefficient",
    )


# -----------------------------------------------------------------------------------------
def _by_segment(c) -> None:
    ui.section(
        "Performance by segment",
        "A model can perform well overall and badly for one group. This is the first check "
        "a fair-lending review runs, and it should be re-run every time the model is "
        "retrained.",
    )

    proba = honest_probabilities(c.book, fingerprint_of(c.book))
    book = c.book.copy()
    book["_proba"] = proba
    cutoff = c.cutoff
    book["_pred"] = (book["_proba"] >= cutoff).astype(int)

    dim = ui.choice("Segment by",
                    ["Property area", "Employment", "Credit history", "Income band"],
                    default="Property area", key="model_seg")
    col = {"Property area": "property_area", "Employment": "employment_status",
           "Credit history": "credit_history", "Income band": "income_bracket"}[dim]

    rows = []
    for name, sub in book.groupby(col, observed=True):
        if len(sub) < 25:
            continue
        y, p, pred = sub["approved"].values, sub["_proba"].values, sub["_pred"].values
        tp = int(((pred == 1) & (y == 1)).sum())
        fp = int(((pred == 1) & (y == 0)).sum())
        fn = int(((pred == 0) & (y == 1)).sum())
        try:
            from sklearn.metrics import roc_auc_score
            auc = roc_auc_score(y, p) if len(set(y)) > 1 else np.nan
        except Exception:
            auc = np.nan
        rows.append({
            "Segment": _pretty(col, name),
            "Applications": len(sub),
            "AUC": auc,
            "Approval rate (model)": (tp + fp) / len(sub) * 100,
            "Approval rate (actual)": float(y.mean()) * 100,
            "Precision": tp / max(tp + fp, 1) * 100,
            "Recall": tp / max(tp + fn, 1) * 100,
        })

    table = pd.DataFrame(rows)
    if table.empty:
        ui.note("No segment in this book is large enough to evaluate separately.", tone="warn")
        return

    ui.table(
        ui.gradient(table.style.format({
            "Applications": "{:,}", "AUC": "{:.3f}",
            "Approval rate (model)": "{:.1f}%", "Approval rate (actual)": "{:.1f}%",
            "Precision": "{:.1f}%", "Recall": "{:.1f}%",
        }), cmap="BuGn", subset=["AUC"], vmin=0.5, vmax=1.0), hide_index=True,
    )

    spread = float(table["AUC"].max() - table["AUC"].min())
    tone = "warn" if spread > 0.08 else "info"
    ui.note(
        f"AUC ranges {spread:.3f} across these segments. A spread above roughly 0.08 means "
        "the model is measurably better at ranking one group than another, which is a "
        "finding to document and monitor even where the approval rates themselves look "
        "even-handed. Compare the model and actual approval rate columns too: a segment "
        "where the model approves noticeably less than the bank did is where disparate "
        "impact would first appear.",
        title="What to escalate", tone=tone,
    )


def _pretty(col: str, value) -> str:
    if col == "credit_history":
        return "History on file" if value == 1 else "No history"
    return str(value).replace("_", "-").title()


def _challenger(c) -> None:
    from src import challenger
    ui.section("Champion vs challenger",
               "Re-trains simpler alternatives on the same data with the same 5-fold split and compares them "
               "with the live model. Nothing here changes the live model; it is evidence for a decision.")
    if st.button("Run comparison", key="chal_run"):
        with st.spinner("Training challengers..."):
            st.session_state["chal_result"] = challenger.compare(c.book, c.model)
    res = st.session_state.get("chal_result")
    if res is not None:
        ui.table(res.style.format({"AUC": "{:.3f}", "Brier": "{:.4f}", "Calibration error": "{:.3f}"}), hide_index=True)
        st.caption("A challenger should beat the champion clearly and consistently before it replaces it, "
                   "and any replacement still goes through your normal model approval.")
