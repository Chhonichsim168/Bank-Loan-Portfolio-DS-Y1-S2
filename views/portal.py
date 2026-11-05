"""
portal.py - the customer portal (v25 design)
============================================
What a bank customer sees after signing in. Nine pages, all reading the SAME database as the staff
pages (loans, payments, requests, messages) but only the rows linked to this customer:

    Home · Pay · Schedule · Apply · Messages · Documents · Notifications · Profile & security · Help

Staff-only information (risk scores, internal notes, follow-up tags, other customers) never reaches
these pages - every query goes through src/customer_portal.py, which filters by the signed-in account.
KHQR payment runs in DEMO mode: the QR is real, but no money moves; "Simulate a successful payment"
records the payment exactly as a confirmed Bakong payment would (see docs/history/CHANGES_v25.md).
"""
from __future__ import annotations

import calendar
import io
import secrets
from datetime import date, timedelta

import pandas as pd
import streamlit as st

from src import audit, auth, customer_portal as portal, khqr, loanbook, ui
from src.customer_i18n import t
from src.data_pipeline import today_local, to_local
from src.security import esc

GREEN, AMBER, RED, TEAL, INK, SOFT = "#16794C", "#B54708", "#B42318", "#0B6B62", "#1B2430", "#5B6676"
PAGES: dict = {}           # filled by app.py: slug -> st.Page, used for links between pages
QR_MINUTES = 15
BANK_LINES = [("Head office", "No. 61, Preah Monivong Blvd, Phnom Penh"), ("Phone", "023 999 888"),
              ("Hours", "Monday-Friday 8:00-16:00 · Saturday 8:00-11:30")]


def cash(value) -> str:
    return f"${float(value):,.2f}"


def _d(x) -> str:
    return pd.Timestamp(x).strftime("%d/%m/%Y") if x is not None and str(x) not in ("", "NaT", "None") else "-"


def _link(slug: str, label: str, **kw) -> None:
    page = PAGES.get(slug)
    if page is not None:
        st.page_link(page, label=label, **kw)


def _css() -> None:
    st.markdown(f"""<style>
    .cp-hero {{ border-radius:16px; padding:18px 22px; margin:.2rem 0 1rem 0; color:#fff;
        display:flex; gap:18px; align-items:center; box-shadow:0 10px 26px rgba(27,36,48,.10); }}
    .cp-hero .big {{ font-size:1.35rem; font-weight:700; }}
    .cp-hero .small {{ opacity:.92; font-size:.92rem; margin-top:2px; }}
    .cp-hero .icon {{ font-size:2.2rem; }}
    .cp-card {{ background:#fff; border:1px solid #E1E6EC; border-radius:14px; padding:14px 16px; height:100%; }}
    .cp-card .lbl {{ color:{SOFT}; font-size:.78rem; text-transform:uppercase; letter-spacing:.05em; font-weight:600; }}
    .cp-card .val {{ color:{INK}; font-size:1.45rem; font-weight:700; margin-top:4px; }}
    .cp-card .sub {{ color:{SOFT}; font-size:.82rem; margin-top:2px; }}
    .cp-bar {{ background:#E7ECF1; border-radius:999px; height:12px; overflow:hidden; margin:6px 0 4px; }}
    .cp-bar > div {{ background:linear-gradient(90deg,#0B6B62,#2BB39B); height:100%; border-radius:999px; }}
    .cp-chip {{ display:inline-block; border-radius:999px; padding:2px 10px; font-size:.78rem; font-weight:700; }}
    .cp-steps {{ display:flex; gap:6px; margin:8px 0 4px; flex-wrap:wrap; }}
    .cp-step {{ flex:1; min-width:92px; text-align:center; font-size:.76rem; padding:6px 4px; border-radius:8px;
        background:#EEF1F4; color:{SOFT}; font-weight:600; }}
    .cp-step.done {{ background:#E3F4EF; color:{TEAL}; }}
    .cp-step.now {{ background:{TEAL}; color:#fff; }}
    .cp-step.bad {{ background:#FDECEA; color:{RED}; }}
    .cp-cal {{ display:grid; grid-template-columns:repeat(7,1fr); gap:5px; }}
    .cp-cal div {{ background:#fff; border:1px solid #E7ECF1; border-radius:8px; min-height:58px; padding:4px 6px;
        font-size:.78rem; color:{SOFT}; }}
    .cp-cal .h {{ background:transparent; border:0; min-height:0; text-align:center; font-weight:700; }}
    .cp-cal .paid {{ background:#E7F6EC; border-color:#A6E0B9; color:{GREEN}; }}
    .cp-cal .over {{ background:#FDECEA; border-color:#F5B5AE; color:{RED}; }}
    .cp-cal .up {{ background:#E8F1FD; border-color:#A9C8F5; color:#1D4ED8; }}
    .cp-cal .today {{ outline:2px solid {TEAL}; }}
    .cp-cal b {{ display:block; color:{INK}; }}
    .cp-note {{ color:{SOFT}; font-size:.85rem; }}
    .cp-notice {{ border-left:4px solid {TEAL}; background:#fff; border-radius:10px; padding:10px 14px;
        margin-bottom:8px; border-top:1px solid #E1E6EC; border-right:1px solid #E1E6EC; border-bottom:1px solid #E1E6EC; }}
    .cp-notice.error {{ border-left-color:{RED}; }} .cp-notice.warning {{ border-left-color:{AMBER}; }}
    .cp-notice.success {{ border-left-color:{GREEN}; }}
    .cp-notice .t {{ font-weight:700; color:{INK}; }} .cp-notice .b {{ color:{SOFT}; font-size:.88rem; }}
    .cp-notice .ts {{ color:#8A96A6; font-size:.75rem; }}
    </style>""", unsafe_allow_html=True)


def _card(label: str, value: str, sub: str = "", color: str = INK) -> None:
    st.markdown(f'<div class="cp-card"><div class="lbl">{esc(label)}</div>'
                f'<div class="val" style="color:{color}">{esc(value)}</div>'
                f'<div class="sub">{sub}</div></div>', unsafe_allow_html=True)


# =========================================================================================
# DATA (all through customer_portal, so only this customer's loans are ever loaded)
# =========================================================================================
def _my() -> list[dict]:
    rows = []
    for lid in portal.my_loans()["loan_id"].tolist():
        loan, snap, sched, pays = portal.loan_details(lid)
        rows.append({"id": lid, "loan": loan, "snap": snap, "sched": sched, "pays": pays,
                     "health": _health(sched, pays), "payoff": _payoff(snap, sched)})
    return rows


def _health(sched: pd.DataFrame, pays: pd.DataFrame) -> dict:
    """Instalments due so far and how many were fully paid on or before their due date."""
    today = today_local().date()
    due = sched[sched["due_date"] <= today]
    events = sorted((pd.Timestamp(p.event_date).date(), float(p.amount)) for p in pays.itertuples())
    on_time, streak, cum_due = 0, 0, 0.0
    for row in due.itertuples():
        cum_due += float(row.installment)
        paid_by_due = sum(a for d, a in events if d <= row.due_date)
        ok = paid_by_due + 0.01 >= cum_due
        on_time += ok
        streak = streak + 1 if ok else 0
    return {"due": len(due), "on_time": on_time, "streak": streak,
            "rate": on_time / len(due) if len(due) else 1.0}


def _payoff(snap: dict, sched: pd.DataFrame) -> dict:
    """Estimate: remaining principal + interest of instalments already due and unpaid."""
    today = today_local().date()
    if snap["status"] != "Active":
        return {"amount": 0.0, "remaining": 0.0, "saving": 0.0}
    overdue = sched[(sched["due_date"] <= today) & (sched["amount_due"] > 0.004)]
    overdue_interest = float((overdue[["interest", "amount_due"]].min(axis=1)).sum())
    amount = round(float(snap["principal_balance"]) + overdue_interest, 2)
    remaining = round(float(sched["amount_due"].sum()), 2)
    return {"amount": amount, "remaining": remaining, "saving": round(max(0.0, remaining - amount), 2)}


def _status(rows: list[dict]) -> tuple[str, str, str, str]:
    """(tone, icon, headline, detail) for the hero banner - the worst loan decides."""
    active = [r for r in rows if r["snap"]["status"] == "Active"]
    if not rows:
        return "neutral", "👋", t("Welcome to Credit Desk"), t("You have no loan with us yet. Apply for one below.")
    if not active:
        return "green", "🎉", t("All your loans are fully repaid"), t("Thank you for banking with us.")
    late = [r for r in active if r["snap"]["arrears"] > 0.004]
    if late:
        worst = max(late, key=lambda r: r["snap"]["dpd"])
        total = sum(r["snap"]["arrears"] for r in late)
        return ("red", "⚠️", t("You are late on a payment") + f" · {worst['snap']['dpd']} " + t("days"),
                t("Overdue amount") + f": <b>{cash(total)}</b>. " + t("Pay now to bring your loan up to date and protect your credit record."))
    nxt = min((r for r in active if r["snap"]["next_due"]), key=lambda r: r["snap"]["next_due"], default=None)
    if nxt:
        days = (nxt["snap"]["next_due"] - today_local().date()).days
        if days <= 3:
            when = t("today") if days == 0 else t("tomorrow") if days == 1 else f"{days} " + t("days")
            return ("amber", "⏰", t("Your next payment is due soon") + f" · {when}",
                    f"{cash(nxt['snap']['next_amount'])} " + t("on") + f" {_d(nxt['snap']['next_due'])}.")
    return "green", "✅", t("You are up to date - thank you!"), t("Every payment so far has been received.")


HERO = {"red": "linear-gradient(135deg,#B42318,#7A1A12)", "amber": "linear-gradient(135deg,#C4650A,#8A4B05)",
        "green": "linear-gradient(135deg,#0B6B62,#07453F)", "neutral": "linear-gradient(135deg,#344054,#1B2430)"}


def _pick_loan(rows: list[dict], key: str) -> dict | None:
    active = [r for r in rows if r["snap"]["status"] == "Active"] or rows
    if not active:
        return None
    if len(active) == 1:
        return active[0]
    labels = {r["id"]: f"{r['id']} · {r['loan']['product']} · {cash(r['loan']['principal'])}" for r in active}
    choice = st.selectbox(t("Choose my loan"), list(labels), format_func=labels.get, key=key)
    return next(r for r in active if r["id"] == choice)


# =========================================================================================
# 1. HOME
# =========================================================================================
def render_home() -> None:
    _css()
    user = auth.current_user()
    _recheck_open_qrs(user)
    prof = portal.profile()
    name = prof.get("full_name") or user.display_name
    rows = _my()
    last = auth._read_users().get(user.username, {}).get("last_login", "")
    ui.page_header(t("Hello") + f", {name}", t("Last sign-in") + f": {to_local(last) if last else '-'}",
                   eyebrow=t("My dashboard"))
    tone, icon, head, detail = _status(rows)
    st.markdown(f'<div class="cp-hero" style="background:{HERO[tone]}"><div class="icon">{icon}</div>'
                f'<div><div class="big">{head}</div><div class="small">{detail}</div></div></div>',
                unsafe_allow_html=True)
    active = [r for r in rows if r["snap"]["status"] == "Active"]
    if active:
        c1, c2, _ = st.columns([1.2, 1.2, 2])
        with c1:
            _link("pay", "💳  " + t("Pay now with KHQR"))
        with c2:
            _link("schedule", "📅  " + t("See my schedule"))

    for r in active:
        loan, snap, h = r["loan"], r["snap"], r["health"]
        ui.section(f"{loan['product']} " + t("loan") + f" · {r['id']}")
        k = st.columns(4, gap="small")
        due_now = snap["arrears"] if snap["arrears"] > 0.004 else snap["next_amount"]
        with k[0]:
            _card(t("Amount to pay"), cash(due_now), t("overdue") if snap["arrears"] > 0.004 else t("next instalment"),
                  RED if snap["arrears"] > 0.004 else INK)
        with k[1]:
            _card(t("Due date"), _d(snap["next_due"]) if snap["arrears"] <= 0.004 else t("Now"),
                  f"{snap['dpd']} " + t("days late") if snap["dpd"] else t("on schedule"),
                  RED if snap["dpd"] else INK)
        with k[2]:
            _card(t("Principal remaining"), cash(snap["principal_balance"]), t("of") + f" {cash(loan['principal'])}")
        with k[3]:
            total = len(r["sched"])
            left = int((r["sched"]["amount_due"] > 0.004).sum())
            _card(t("Months remaining"), f"{left} / {total}", t("Loan ends") + f" {_d(snap.get('maturity_date'))}")
        repaid = 1 - snap["principal_balance"] / float(loan["principal"]) if float(loan["principal"]) else 0
        st.markdown(f'<div class="cp-note" style="margin-top:.8rem">' + t("You have repaid")
                    + f' <b>{repaid:.0%}</b> ' + t("of the money you borrowed")
                    + f'</div><div class="cp-bar"><div style="width:{repaid * 100:.1f}%"></div></div>'
                    f'<div class="cp-note">🎯 ' + t("Debt-free on") + f' <b>{_d(snap.get("maturity_date"))}</b>'
                    + (f' · ' + t("pay it off early to save about") + f' <b>{cash(r["payoff"]["saving"])}</b>'
                       if r["payoff"]["saving"] > 1 else "") + '</div>', unsafe_allow_html=True)
        _health_panel(h)

    closed = [r for r in rows if r["snap"]["status"] != "Active"]
    if closed:
        ui.section(t("Repaid loans"))
        for r in closed:
            st.markdown(f"✅ **{r['id']}** · {r['loan']['product']} · {cash(r['loan']['principal'])} · "
                        + t("fully repaid"))
    if not rows:
        _link("apply", "📝  " + t("Apply for a loan"))

    ui.section(t("Latest updates"))
    notes = portal.my_notifications()[:3]
    if not notes:
        st.caption(t("No updates yet."))
    for n in notes:
        _notice(n)
    _link("notifications", t("See all notifications") + "  →")


def _recheck_open_qrs(user) -> None:
    """A QR paid after the customer left the Pay page is found and recorded here."""
    from src import qr_payments
    showing = (st.session_state.get("_cp_qr") or {}).get("md5", "")      # the Pay page checks that one itself
    try:
        found = qr_payments.recheck(user.username, skip=(showing,) if showing else ())
    except Exception:
        found = []
    for f in found:
        st.success("✅ " + t("We received your payment") + f" {cash(f['amount'])} ({f['ref']}). "
                   + t("Your receipt is in My documents."))


def _health_panel(h: dict) -> None:
    if not h["due"]:
        return
    rate = h["rate"]
    color = GREEN if rate >= .95 else AMBER if rate >= .8 else RED
    badge = ("🏅 " + t("Excellent payer - 1 year on time") if h["streak"] >= 12 else
             "⭐ " + t("Reliable payer") if h["streak"] >= 6 else
             "🌱 " + t("Building your record") if rate >= .8 else "⚠️ " + t("Needs attention"))
    tip = (t("Keep it up: customers with 12 on-time months can ask for a lower rate on their next loan.")
           if h["streak"] >= 12 else
           t("Pay on time for") + f" {max(1, 6 - h['streak'] if h['streak'] < 6 else 12 - h['streak'])} "
           + t("more month(s) to reach the next badge.") if rate >= .8 else
           t("Bring your loan up to date - your on-time record starts growing again from the next payment."))
    st.markdown(f'<div class="cp-card" style="margin-top:.7rem"><div class="lbl">' + t("Payment record")
                + f'</div><div style="display:flex;gap:14px;align-items:center;flex-wrap:wrap;margin-top:4px">'
                f'<div class="val" style="color:{color}">{h["on_time"]}/{h["due"]}</div>'
                f'<div class="sub">' + t("payments on time") + f' ({rate:.0%})</div>'
                f'<span class="cp-chip" style="background:#F2F4F7;color:{INK}">{badge}</span></div>'
                f'<div class="sub" style="margin-top:6px">💡 {tip}</div></div>', unsafe_allow_html=True)


def _notice(n: dict) -> None:
    st.markdown(f'<div class="cp-notice {esc(n.get("tone", "info"))}">'
                f'<div class="t">{"🔵 " if n.get("unread") else ""}{esc(t(n["title"]))}</div>'
                f'<div class="b">{esc(n["body"])}</div><div class="ts">{esc(to_local(n["ts"]) if n.get("ts") else "")}</div>'
                '</div>', unsafe_allow_html=True)


# =========================================================================================
# 2. PAY
# =========================================================================================
def _qr_png(text: str) -> bytes | None:
    try:
        import qrcode
    except ImportError:
        return None
    img = qrcode.make(text, box_size=8, border=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def render_pay() -> None:
    _css()
    user = auth.current_user()
    ui.page_header(t("Make a payment"), t("Pay with any Cambodian bank app that scans KHQR (ABA, ACLEDA, Wing ...)."),
                   eyebrow=t("Payments"))
    _recheck_open_qrs(user)
    rows = _my()
    if st.session_state.get("_cp_flash_pay"):
        st.success(st.session_state.pop("_cp_flash_pay"))
    receipt = st.session_state.get("_cp_receipt")
    if receipt and receipt.get("user") == user.username:
        _receipt(receipt)
        return
    r = _pick_loan([x for x in rows if x["snap"]["status"] == "Active"], "cp_pay_loan")
    if r is None:
        st.info(t("You have no loan to pay right now."))
        return
    snap, pay = r["snap"], r["payoff"]
    state = st.session_state.get("_cp_qr")
    if state and (state.get("loan") != r["id"] or state.get("user") != user.username):
        state = None
    if not state:
        options = {}
        sched = r["sched"]
        coming = sched[(sched["due_date"] > today_local().date()) & (sched["amount_due"] > 0.004)]
        nxt_date, nxt_amt = (coming["due_date"].iloc[0], float(coming["amount_due"].iloc[0])) if len(coming) else (None, 0.0)
        if snap["arrears"] > 0.004:
            options["overdue"] = (t("Everything overdue"), snap["arrears"])
        if nxt_amt > 0.004:
            options["next"] = (t("Next instalment") + f" ({_d(nxt_date)})", nxt_amt)
        if snap["arrears"] > 0.004 and nxt_amt > 0.004:
            options["both"] = (t("Overdue + next instalment"), snap["arrears"] + nxt_amt)
        if pay["amount"] > 0.004:
            options["payoff"] = (t("Pay off the whole loan"), pay["amount"])
        options["other"] = (t("Another amount"), 0.0)
        left, right = st.columns([1.2, 1], gap="large")
        with left:
            ui.section(t("How much do you want to pay?"))
            choice = st.radio(t("Amount"), list(options), key="cp_pay_choice", label_visibility="collapsed",
                              format_func=lambda k: f"{options[k][0]}" + (f" · {cash(options[k][1])}" if k != "other" else ""))
            amount = options[choice][1]
            if choice == "other":
                amount = st.number_input(t("Amount (USD)"), min_value=0.01, max_value=float(max(pay["remaining"], 0.01)),
                                         value=float(max(0.01, round(snap["next_amount"], 2))), step=10.0, key="cp_pay_other")
            if st.button(t("Create KHQR code"), type="primary", key="cp_make_qr"):
                _make_qr(user, r["id"], round(float(amount), 2), "settle" if choice == "payoff" else "payment")
                st.rerun()
        with right:
            ui.section(t("Pay off early?"))
            if pay["amount"] > 0.004:
                _card(t("Pay-off amount today (estimate)"), cash(pay["amount"]),
                      t("instead of") + f" {cash(pay['remaining'])} " + t("still scheduled") + " · "
                      + t("you save about") + f" <b style='color:{GREEN}'>{cash(pay['saving'])}</b>", TEAL)
                st.caption(t("Estimate only: remaining principal plus interest already due. The bank confirms the exact amount."))
        _help_box(r)
        return

    # QR step
    remaining = (pd.Timestamp(state["expires"]) - pd.Timestamp.now()).total_seconds()
    if remaining <= 0:
        st.warning(t("This QR code has expired. Create a new one."))
        if st.button(t("Create a new code"), key="cp_qr_expired"):
            st.session_state.pop("_cp_qr", None)
            st.rerun()
        return
    left, right = st.columns([1, 1.2], gap="large")
    with left:
        st.markdown(f'<div style="border:1px solid #E1E6EC;border-radius:16px;overflow:hidden;max-width:300px;background:#fff">'
                    f'<div style="background:#E1232E;color:#fff;font-weight:800;text-align:center;padding:8px;'
                    f'letter-spacing:.1em">KHQR</div><div style="padding:10px 16px 0">'
                    f'<div class="cp-note">{esc(state["payee"])}</div><div style="font-size:1.6rem;font-weight:800">'
                    f'{state["charge_label"]}</div></div></div>', unsafe_allow_html=True)
        png = _qr_png(state["qr"])
        if png:
            st.image(png, width=260)
            st.download_button("📥 " + t("Save QR to my phone"), png, file_name=f"KHQR_{state['ref']}.png",
                               mime="image/png", key="cp_qr_save")
            st.caption(t("Paying on this same phone? Save the QR, then in ABA tap Scan → Gallery and choose it."))
        else:
            st.code(state["qr"], language=None)
        st.caption(f"⏱ " + t("Expires in") + f" {int(remaining // 60)}:{int(remaining % 60):02d} · {state['ref']}")
    with right:
        ui.section(t("Scan and pay"))
        st.markdown("1. " + t("Open ABA Mobile, ACLEDA or any bank app") + "\n2. " + t("Tap Scan and point at the QR")
                    + "\n3. " + t("Check the amount and confirm"))
        if not state["real"]:
            ui.note(t("Demo mode: this QR is not linked to a real bank account and no money moves. Press the button "
                      "below to record the payment exactly as a confirmed Bakong payment would."),
                    title=t("School demo"), tone="warn")
            if st.button("✅ " + t("Simulate a successful payment (demo)"), type="primary", key="cp_qr_paid"):
                _record_payment(user, state)
        else:
            if state["charge"] != state["amount"]:
                ui.note(t("Test mode: the QR charges") + f" <b>{state['charge_label']}</b> " + t("but records")
                        + f" <b>{cash(state['amount'])}</b> " + t("on the loan (set test_amount = 0 in secrets.toml "
                                                                     "for real amounts)."), title=t("Test payment"), tone="warn")
            if khqr.can_check():
                _auto_check(user)
                if st.button(t("I have paid - check now"), type="primary", key="cp_qr_check"):
                    _check_once(user, state)
            st.caption(t("Paid but not confirmed automatically? Send it to the bank - a staff member checks the bank "
                         "account and confirms it."))
            if st.button(t("I have paid - ask the bank to confirm"), key="cp_qr_manual"):
                _send_for_confirmation(user, state)
        if st.button(t("Cancel"), key="cp_qr_cancel"):
            st.session_state.pop("_cp_qr", None)
            st.rerun()


def _make_qr(user, loan_id: str, amount: float, kind: str) -> None:
    ref = "CD" + secrets.token_hex(4).upper()
    state = {"user": user.username, "loan": loan_id, "amount": amount, "kind": kind, "ref": ref,
             "expires": (pd.Timestamp.now() + pd.Timedelta(minutes=QR_MINUTES)).isoformat(), "checks": 0}
    if khqr.configured():
        cur = khqr.settings()["currency"]
        charge = khqr.test_amount() or amount
        qr = khqr.build(charge, cur, bill=ref, minutes=QR_MINUTES)
        state.update(real=True, qr=qr, md5=khqr.md5(qr), charge=charge, payee=khqr.merchant_name(),
                     charge_label=(f"${charge:,.2f}" if cur == "USD" else f"{int(charge):,} ៛"))
        from src import qr_payments
        qr_payments.register(user.username, state)
    else:
        state.update(real=False, qr=f"KHQR DEMO|Credit Desk G4|{loan_id}|USD {amount:.2f}|{ref}", md5="",
                     charge=amount, payee="Credit Desk G4", charge_label=cash(amount))
    st.session_state["_cp_qr"] = state


MAX_CHECKS = 60          # 5 minutes of automatic checks per QR (the Bakong token allows 100 a day)


def _auto_check(user) -> None:
    @st.fragment(run_every=5)
    def poll():
        state = st.session_state.get("_cp_qr")
        if not state or not state.get("real"):
            return
        if state["checks"] >= MAX_CHECKS:
            st.caption(t("Automatic checking stopped. Press 'I have paid - check now' after paying."))
            return
        state["checks"] += 1
        status, data = khqr.check(state["md5"])
        if status == "paid":
            _record_payment(user, state, data, scope="app")
        elif status == "error":
            state["checks"] = MAX_CHECKS
            st.warning(str(data))
        else:
            st.markdown('<div class="cp-note">⟳ ' + t("Waiting for your payment") + f" ({state['checks']})</div>",
                        unsafe_allow_html=True)
    poll()


def _check_once(user, state: dict) -> None:
    status, data = khqr.check(state["md5"])
    if status == "paid":
        _record_payment(user, state, data)
    elif status == "unpaid":
        st.info(t("Bakong has not received this payment yet. Wait a few seconds and check again."))
    else:
        st.warning(str(data))


def _send_for_confirmation(user, state: dict) -> None:
    from src import customer_payments
    try:
        customer_payments.submit(state["loan"], state["amount"], today_local().date(),
                                 f"KHQR {state['ref']} (md5 {state['md5'][:10]})")
        if state.get("md5"):
            from src import qr_payments
            qr_payments.mark(state["md5"], "reported")
    except (ValueError, PermissionError, audit.AuditError) as exc:
        st.error(str(exc))
        return
    st.session_state.pop("_cp_qr", None)
    st.session_state["_cp_flash_pay"] = t("Sent. The bank will confirm your payment and your receipt will appear "
                                          "in My documents.")
    st.rerun()


def _record_payment(user, state: dict, bakong: dict | None = None, scope: str = "") -> None:
    """Write the payment to the Loan book once (src/qr_payments.record) and show the receipt."""
    from src import qr_payments
    try:
        eid = qr_payments.record(user.username, state["loan"], state["amount"], state["kind"], state["ref"],
                                 state.get("md5", ""), bakong)
    except (ValueError, PermissionError, audit.AuditError) as exc:
        st.error(str(exc))
        return
    st.session_state.pop("_cp_qr", None)
    if not eid and state.get("md5"):
        eid = qr_payments.event_for(state["md5"])           # recorded a moment ago by another check
    if eid:
        st.session_state["_cp_receipt"] = {"user": user.username, "loan": state["loan"], "event": int(eid),
                                           "amount": state["amount"], "ref": state["ref"], "kind": state["kind"],
                                           "bakong": str((bakong or {}).get("hash", ""))[:16]}
    st.rerun(**({"scope": scope} if scope else {}))


def _receipt(rc: dict) -> None:
    loan, snap, _, pays = portal.loan_details(rc["loan"])
    p = pays[pays["id"] == rc["event"]]
    st.markdown(f'<div class="cp-hero" style="background:{HERO["green"]}"><div class="icon">✅</div><div>'
                f'<div class="big">' + t("Payment successful") + f'</div><div class="small">{cash(rc["amount"])} · '
                f'{rc["loan"]} · {rc["ref"]}</div></div></div>', unsafe_allow_html=True)
    k = st.columns(4)
    with k[0]:
        _card(t("Receipt"), f"PAY-{rc['event']:08d}", _d(today_local().date()))
    with k[1]:
        _card(t("Principal repaid"), cash(p["principal_paid"].iloc[0]) if len(p) else "-")
    with k[2]:
        _card(t("Interest paid"), cash(p["interest_paid"].iloc[0]) if len(p) else "-")
    with k[3]:
        _card(t("Still overdue"), cash(snap["arrears"]), t("Loan closed") if snap["status"] != "Active" else
              t("Next due") + f" {_d(snap['next_due'])}", GREEN if snap["arrears"] < .005 else RED)
    c1, c2 = st.columns(2)
    try:
        c1.download_button(t("Download receipt (PDF)"), portal.payment_receipt(rc["loan"], rc["event"]),
                           file_name=f"receipt_PAY-{rc['event']:08d}.pdf", mime="application/pdf", key="cp_rc_pdf",
                           type="primary")
    except Exception as exc:                                 # PDF library missing
        c1.caption(str(exc))
    if c2.button(t("Done"), key="cp_rc_done"):
        st.session_state.pop("_cp_receipt", None)
        st.rerun()
    st.caption(t("The bank has been notified automatically - no need to send a screenshot."))


def _help_box(r: dict) -> None:
    from src import customer_support
    with st.expander("🆘 " + t("Having trouble paying? Ask the bank for help")):
        st.caption(t("Tell us early. The bank can discuss a new date or a restructured schedule - it is better than "
                     "missing payments."))
        with st.form("cp_help_form", clear_on_submit=True):
            reason = st.selectbox(t("What happened?"), [t("Lost income / job"), t("Illness or family emergency"),
                                                        t("Business is slow"), t("Other")])
            msg = st.text_area(t("Tell us more"), max_chars=1000)
            go = st.form_submit_button(t("Send to my loan officer"), type="primary")
        if go:
            try:
                customer_support.create_ticket(f"Payment help: {reason}", msg or reason, loan_id=r["id"])
                st.success(t("Sent. Your loan officer will reply in Messages."))
            except (ValueError, PermissionError) as exc:
                st.error(str(exc))


# =========================================================================================
# 3. SCHEDULE
# =========================================================================================
def render_schedule() -> None:
    _css()
    ui.page_header(t("Repayment schedule"), t("Every instalment, what is paid and what is still to come."),
                   eyebrow=t("My loans"))
    rows = _my()
    r = _pick_loan(rows, "cp_sched_loan")
    if r is None:
        st.info(t("You have no loan yet."))
        return
    sched = r["sched"].copy()
    today = today_local().date()
    months = sorted({f"{d.year}-{d.month:02d}" for d in sched["due_date"]})
    cur = f"{today.year}-{today.month:02d}"
    default = cur if cur in months else months[0]
    ym = st.select_slider(t("Month"), options=months, value=default, key=f"cp_cal_{r['id']}",
                          format_func=lambda x: f"{calendar.month_abbr[int(x[5:])]} {x[:4]}")
    _calendar(sched, (int(ym[:4]), int(ym[5:])), today)
    st.markdown(f'<div class="cp-note" style="margin:.4rem 0 1rem">🟩 ' + t("Paid") + ' &nbsp; 🟥 ' + t("Overdue")
                + ' &nbsp; 🟦 ' + t("Upcoming") + '</div>', unsafe_allow_html=True)
    ui.section(t("All instalments"))
    view = pd.DataFrame({
        "#": sched["no"] if "no" in sched else range(1, len(sched) + 1),
        t("Due date"): [d.strftime("%d/%m/%Y") for d in sched["due_date"]],
        t("Instalment"): sched["installment"].map(cash),
        t("Principal"): sched["principal"].map(cash) if "principal" in sched else "",
        t("Interest"): sched["interest"].map(cash),
        t("Paid"): sched["paid"].map(cash),
        t("Status"): sched["payment_status"].map(lambda s: {"Paid": "✅ ", "Overdue": "🔴 ", "Upcoming": "🔵 "}[s] + t(s)),
        t("Balance after"): sched["balance"].map(cash) if "balance" in sched else ""})
    ui.table(view, height=min(460, 60 + 35 * len(view)))
    c1, c2 = st.columns(2)
    try:
        c1.download_button(t("Download schedule (PDF)"), portal.repayment_schedule_pdf(r["id"]),
                           file_name=f"schedule_{r['id']}.pdf", mime="application/pdf", key="cp_sched_pdf")
    except Exception:
        pass
    c2.download_button(t("Download schedule (Excel / CSV)"), view.to_csv(index=False).encode("utf-8-sig"),
                       file_name=f"schedule_{r['id']}.csv", mime="text/csv", key="cp_sched_csv")


def _calendar(sched: pd.DataFrame, ym: tuple[int, int], today: date) -> None:
    y, m = ym
    by_day = {d.day: row for d, row in zip(sched["due_date"], sched.itertuples()) if d.year == y and d.month == m}
    cells = [f'<div class="h">{d}</div>' for d in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")]
    first_wd, days = calendar.monthrange(y, m)
    cells += ['<div style="visibility:hidden"></div>'] * first_wd
    for day in range(1, days + 1):
        row = by_day.get(day)
        cls = ""
        body = ""
        if row is not None:
            cls = {"Paid": "paid", "Overdue": "over", "Upcoming": "up"}[row.payment_status]
            body = f"<b>{cash(row.installment)}</b>{t(row.payment_status)}"
        if date(y, m, day) == today:
            cls += " today"
        cells.append(f'<div class="{cls}">{day}{body}</div>')
    st.markdown(f'<div class="cp-cal">{"".join(cells)}</div>', unsafe_allow_html=True)


# =========================================================================================
# 4. APPLY
# =========================================================================================
STEPS = ["Submitted", "Under review", "First approval", "Second approval (four-eyes)", "Money issued"]


def render_apply() -> None:
    _css()
    ui.page_header(t("Apply for a loan"), t("Try the calculator, check if it fits your budget, then send your request."),
                   eyebrow=t("Loan requests"))
    left, right = st.columns([1.1, 1], gap="large")
    with left:
        ui.section(t("1 · Loan calculator"))
        product = st.selectbox(t("Loan product"), loanbook.PRODUCTS, key="cp_ap_product")
        amount = st.slider(t("Loan amount ($)"), 500, 50_000, 5_000, step=500, key="cp_ap_amount")
        term = st.select_slider(t("Term (months)"), options=[6, 12, 18, 24, 36, 48, 60, 84, 120],
                                value=24, key="cp_ap_term")
        est = portal.estimate_terms(amount, term, 10.0)
        k = st.columns(3)
        with k[0]:
            _card(t("Monthly payment"), cash(est["monthly_payment"]), t("estimate"), TEAL)
        with k[1]:
            _card(t("Total interest"), cash(est["total_interest"]), "10% " + t("flat"))
        with k[2]:
            _card(t("Total repayment"), cash(est["total_repayment"]))
    with right:
        ui.section(t("2 · Does it fit my budget?"))
        income = st.number_input(t("My monthly income ($)"), min_value=0.0, value=800.0, step=50.0, key="cp_ap_income")
        other = st.number_input(t("Other monthly debt payments ($)"), min_value=0.0, value=0.0, step=10.0, key="cp_ap_other")
        dti = (est["monthly_payment"] + other) / income if income else 9.9
        tone, msg = ((GREEN, t("Looks affordable")) if dti <= .35 else (AMBER, t("Possible - the bank will look closely"))
                     if dti <= .5 else (RED, t("Too high - try a smaller amount or a longer term")))
        _card(t("Share of income for debts"), f"{dti:.0%}", f'<b style="color:{tone}">{msg}</b> · '
              + t("banks usually look for 40% or less"), tone)
        st.caption(t("Quick check only - not a decision. A loan officer reviews every request."))

    ui.section(t("3 · Send my request"))
    if not portal.profile():
        st.warning(t("Complete your profile (name, phone, address) before sending a request."))
        _link("profile", "👤  " + t("Complete my profile"))
    else:
        with st.form("cp_apply_form", clear_on_submit=True):
            purpose = st.text_area(t("What will you use the loan for?"), max_chars=2000, key="cp_ap_purpose")
            ok = st.checkbox(t("The information I give is true."), key="cp_ap_ok")
            go = st.form_submit_button(t("Send my request") + f" · {cash(amount)} / {term} " + t("months"),
                                       type="primary")
        if go:
            if not ok or not purpose.strip():
                st.error(t("Describe the purpose and tick the box."))
            else:
                try:
                    rid = portal.submit_request(float(amount), int(term), product, purpose, estimated_rate=10.0)
                    st.success(t("Request sent") + f": {rid}. " + t("Upload your documents below to speed it up."))
                except (ValueError, PermissionError, audit.AuditError) as exc:
                    st.error(str(exc))

    reqs = portal.requests()
    if reqs.empty:
        return
    ui.section(t("My requests"))
    if st.session_state.get("_cp_flash"):
        st.success(st.session_state.pop("_cp_flash"))
    for r in reqs.itertuples():
        _request_card(r)


def _request_card(r) -> None:
    from src import customer_documents, documents
    status = r.status
    issued = isinstance(r.loan_id, str) and bool(r.loan_id)
    second = isinstance(getattr(r, "second_approver", None), str) or (status == "Approved" and not portal.four_eyes_required())
    stage = 4 if issued else 4 if second else 3 if status == "Approved" else 2 if status == "Declined" else 1
    html = []
    for i, name in enumerate(STEPS):
        label, cls = t(name), "done" if i < stage else "now" if i == stage else ""
        if status == "Declined" and i == 2:
            label, cls = t("Declined"), "bad"
        if status == "Declined" and i > 2:
            label, cls = "-", ""
        if status == "Cancelled":
            label, cls = (t("Cancelled"), "bad") if i == 1 else (label if i == 0 else "-", "done" if i == 0 else "")
        if issued and i == 4:
            cls = "done"
        html.append(f'<div class="cp-step {cls}">{esc(label)}</div>')
    with st.container(border=True):
        st.markdown(f"**{r.request_id}** · {r.product} · {cash(r.amount)} · {int(r.term_months)} " + t("months")
                    + f" · {_d(r.submitted_at)}")
        st.markdown(f'<div class="cp-steps">{"".join(html)}</div>', unsafe_allow_html=True)
        if r.explanation:
            st.caption(t("Message from the bank") + f": {r.explanation}")
        if status == "Approved" and not issued:
            st.caption("🛡️ " + (t("Approved by two bank officers - the money is being prepared.") if second else
                               t("Approved by your loan officer. A second officer is doing the final check "
                                 "(four-eyes rule) before the money is issued.")))
        if status == "Pending review":
            docs = customer_documents.for_request(r.request_id)
            if len(docs):
                st.caption(t("Documents") + ": " + ", ".join(f"{d.kind} ({t(d.status)})" for d in docs.itertuples()))
                for d in docs.itertuples():
                    if d.note:
                        st.info(f"{d.kind}: {d.note}")
            c1, c2, c3 = st.columns([1.3, 2.2, 1])
            kind = c1.selectbox(t("Document type"), documents.KINDS, key=f"cp_doc_kind_{r.request_id}")
            up = c2.file_uploader(t("Upload (PDF, JPG, PNG)"), type=["pdf", "png", "jpg", "jpeg"],
                                  key=f"cp_doc_{r.request_id}_{st.session_state.get('_cp_doc_n', 0)}")
            if up is not None and c3.button(t("Attach"), key=f"cp_doc_go_{r.request_id}"):
                try:
                    customer_documents.attach(r.request_id, up.getvalue(), up.name, kind)
                    st.session_state["_cp_doc_n"] = st.session_state.get("_cp_doc_n", 0) + 1
                    st.rerun()
                except (ValueError, PermissionError, audit.AuditError) as exc:
                    st.error(str(exc))
            if st.button(t("Cancel request"), key=f"cp_cancel_{r.request_id}"):
                try:
                    portal.cancel_request(r.request_id)
                    st.session_state["_cp_flash"] = t("Request") + f" {r.request_id} " + t("has been cancelled.")
                    st.rerun()
                except (ValueError, PermissionError) as exc:
                    st.error(str(exc))


# =========================================================================================
# 5. DOCUMENTS
# =========================================================================================
def render_documents() -> None:
    _css()
    ui.page_header(t("My documents"), t("Statements, schedules and receipts - ready to download."), eyebrow=t("Documents"))
    rows = _my()
    if not rows:
        st.info(t("Documents appear here once you have a loan."))
    for r in rows:
        ui.section(f"{r['id']} · {r['loan']['product']}")
        c = st.columns(3)
        for col, (label, fn, name) in zip(c, [(t("Loan statement"), portal.loan_statement, "statement"),
                                              (t("Repayment schedule"), portal.repayment_schedule_pdf, "schedule"),
                                              (t("Pay-off letter"), _payoff_letter, "payoff_letter")]):
            with col:
                if name == "payoff_letter" and r["snap"]["status"] == "Active":
                    _card(label, "🔒", t("Available when the loan is fully repaid"))
                    continue
                try:
                    st.download_button(f"⬇ {label} (PDF)", fn(r["id"]), file_name=f"{name}_{r['id']}.pdf",
                                       mime="application/pdf", key=f"cp_dl_{name}_{r['id']}")
                except Exception as exc:
                    st.caption(str(exc))
        pays = r["pays"]
        if len(pays):
            st.markdown("**" + t("Payment receipts") + "**")
            for p in pays.sort_values("event_date", ascending=False).head(12).itertuples():
                a, b = st.columns([3, 1])
                a.markdown(f"🧾 PAY-{int(p.id):08d} · {_d(p.event_date)} · **{cash(p.amount)}**")
                try:
                    b.download_button(t("Receipt"), portal.payment_receipt(r["id"], int(p.id)),
                                      file_name=f"receipt_PAY-{int(p.id):08d}.pdf", mime="application/pdf",
                                      key=f"cp_rc_{p.id}")
                except Exception:
                    pass
    reqs = portal.requests()
    if len(reqs):
        ui.section(t("Request confirmations"))
        for q in reqs.itertuples():
            a, b = st.columns([3, 1])
            a.markdown(f"📝 {q.request_id} · {q.product} · {cash(q.amount)} · {t(q.status)}")
            try:
                b.download_button("PDF", portal.request_receipt(q.request_id), file_name=f"{q.request_id}.pdf",
                                  mime="application/pdf", key=f"cp_rq_{q.request_id}")
            except Exception:
                pass


def _payoff_letter(loan_id: str) -> bytes:
    from src import reports
    loan, snap, _, pays = portal.loan_details(loan_id)
    name = portal.profile().get("full_name") or auth.current_user().display_name
    last = pays["event_date"].max() if len(pays) else today_local().date()
    return reports.receipt_pdf(title="Loan pay-off letter", number=f"POL-{loan_id}", issued=to_local(audit._now()),
                               status="Loan fully repaid", signatures=("Credit Desk",),
                               rows=[("Customer", name), ("Loan reference", loan_id), ("Product", loan["product"]),
                                     ("Amount borrowed", cash(loan["principal"])),
                                     ("Total paid", cash(pays["amount"].sum() if len(pays) else 0)),
                                     ("Last payment", _d(last)), ("Balance", "$0.00")],
                               note="This letter confirms that the loan above has been repaid in full and that the "
                                    "customer owes nothing more on it.")


# =========================================================================================
# 6. NOTIFICATIONS
# =========================================================================================
def render_notifications() -> None:
    _css()
    ui.page_header(t("Notifications"), t("Payments, reminders, decisions and replies."), eyebrow=t("Updates"))
    notes = st.session_state.get("_cp_notes") or portal.my_notifications()
    if not notes:
        st.info(t("No notifications yet."))
    for n in notes:
        _notice(n)
    portal.mark_notifications_read([n["id"] for n in notes])


# =========================================================================================
# 7. PROFILE & SECURITY
# =========================================================================================
def render_profile() -> None:
    _css()
    user = portal.require_role("customer", *portal.STAFF)
    prof = portal.profile()
    ui.page_header(t("Profile & security"), t("Your details, your photo and who signed in to your account."),
                   eyebrow=t("Account"))
    left, right = st.columns([1, 2.2], gap="large")
    with left:
        photo = portal.profile_photo()
        if photo:
            st.image(photo, width=170)
        else:
            initials = "".join(w[0] for w in (prof.get("full_name") or user.display_name).split()[:2]).upper()
            st.markdown(f'<div style="width:150px;height:150px;border-radius:50%;background:#D3F4EC;color:#07453F;'
                        f'display:flex;align-items:center;justify-content:center;font-size:2.6rem;font-weight:700;'
                        f'border:3px solid #87DACA">{esc(initials)}</div>', unsafe_allow_html=True)
        up = st.file_uploader(t("Change photo"), type=["jpg", "jpeg", "png", "webp"], key="cp_photo")
    with right:
        filled = sum(bool(prof.get(k)) for k in ("full_name", "phone", "location"))
        st.markdown(f'<div class="cp-note">' + t("Profile complete") + f': <b>{filled}/3</b></div>'
                    f'<div class="cp-bar"><div style="width:{filled / 3 * 100:.0f}%"></div></div>',
                    unsafe_allow_html=True)
        with st.form("cp_profile", border=True):
            name = st.text_input(t("Full name"), value=prof.get("full_name", user.display_name), max_chars=120)
            phone = st.text_input(t("Phone number"), value=prof.get("phone", ""), max_chars=60)
            email = st.text_input(t("Email"), value=prof.get("email", "") or auth.account_email(user.username)["email"],
                                  max_chars=200, help=t("Your sign-in email is changed in My account."))
            location = st.text_area(t("Location / address"), value=prof.get("location", ""), max_chars=300)
            save = st.form_submit_button(t("Save my profile"), type="primary")
        if save:
            try:
                portal.save_profile(name, phone, email, location, photo=up.getvalue() if up is not None else None)
                st.success(t("Your profile has been saved."))
                st.rerun()
            except (ValueError, PermissionError, audit.AuditError) as exc:
                st.error(str(exc))
    ui.section(t("Sign-in and security"))
    info = auth.account_email(user.username)
    c = st.columns(3)
    with c[0]:
        _card(t("Sign-in email"), info["email"] or "-", ("✅ " + t("Verified")) if info["verified"] else t("Not verified"))
    with c[1]:
        _card(t("Sign-in methods"), " + ".join((["Google"] if info["google"] else []) + ([t("Password")] if info["password"] else [])) or "-")
    with c[2]:
        _card(t("Two-step sign-in"), t("On") if user.mfa_enabled else t("Off"))
    _link("account", "🔐  " + t("Change password, email or two-step sign-in") + "  →")
    ui.section(t("Recent sign-ins"))
    ev = audit.fetch_events(3000)
    ev = ev[(ev["username"] == user.username) & ev["action"].isin(["login", "logout", "login_failed", "session_timeout",
                                                                   "password_recovered", "password_changed"])].head(10)
    if ev.empty:
        st.caption(t("No sign-ins recorded yet."))
    else:
        names = {"login": "✅ " + t("Signed in"), "logout": "↩ " + t("Signed out"), "login_failed": "⚠️ " + t("Wrong password"),
                 "session_timeout": "⏱ " + t("Signed out (idle)"), "password_recovered": "🔑 " + t("Password reset"),
                 "password_changed": "🔑 " + t("Password changed")}
        ui.table(pd.DataFrame({t("When"): to_local(ev["ts"]), t("What"): ev["action"].map(names)}), height=min(380, 60 + 35 * len(ev)))
        st.caption(t("Not you? Change your password now in My account and tell the bank in Messages."))


# =========================================================================================
# 8. HELP
# =========================================================================================
FAQ = [
    ("How is my interest calculated?", "Your loan uses a fixed monthly instalment. Each payment first pays the "
     "interest for the month, the rest reduces the money you borrowed (the principal). As the principal falls, "
     "more of each payment goes to principal."),
    ("What happens if I pay late?", "The instalment shows as overdue, your on-time record stops growing and the "
     "bank's collection team contacts you. Pay as soon as you can, or ask for help in Messages - the bank can "
     "agree a new date or a new schedule."),
    ("Can I pay off my loan early?", "Yes. Open Pay and choose 'Pay off the whole loan'. You pay the remaining "
     "principal plus interest already due, and save the future interest."),
    ("How do I pay with KHQR?", "Open Pay, choose the amount, press Create KHQR code and scan it with ABA, ACLEDA, "
     "Wing or any Cambodian bank app. Your receipt appears straight away and the bank is told automatically."),
    ("Where are my receipts?", "In Documents. Every payment has its own PDF receipt."),
    ("I forgot my password.", "On the sign-in page press 'Forgot password?' - we email you a 6-digit code. If you "
     "signed up with Google, just press Continue with Google."),
]
GLOSSARY = [("Principal", "The money you borrowed."), ("Interest", "The price of borrowing, paid every month."),
            ("Instalment", "The fixed amount you pay each month (principal + interest)."),
            ("Overdue / arrears", "Instalments that were due but are not paid yet."),
            ("Pay-off amount", "What you pay today to close the loan completely."),
            ("Restructure", "A new schedule agreed with the bank when you have difficulty paying.")]


def render_help() -> None:
    _css()
    ui.page_header(t("Help"), t("Answers to common questions, simple words, and how to reach us."), eyebrow=t("Help"))
    left, right = st.columns([1.5, 1], gap="large")
    with left:
        ui.section(t("Questions and answers"))
        for q, a in FAQ:
            with st.expander(t(q)):
                st.write(t(a))
        ui.section(t("Money words made simple"))
        ui.table(pd.DataFrame([{t("Word"): t(w), t("Meaning"): t(m)} for w, m in GLOSSARY]), height=270)
    with right:
        ui.section(t("Contact the bank"))
        for k, v in BANK_LINES:
            st.markdown(f"**{t(k)}** · {v}")
        _link("support", "💬  " + t("Send a message to my loan officer") + "  →")
        st.caption(t("The bank will never ask for your password or a code we emailed you."))
