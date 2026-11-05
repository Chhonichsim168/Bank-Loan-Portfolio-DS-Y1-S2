"""
mailer.py
=========
Sends Credit Desk's emails (sign-up verification codes and password-reset codes) through an
SMTP account - for a school project a Gmail address with an "App password" is the simplest.

Turned on by an ``[email]`` section in ``.streamlit/secrets.toml``::

    [email]
    sender   = "creditdesk.g4@gmail.com"     # the Gmail account that sends
    password = "abcd efgh ijkl mnop"         # its 16-letter App password (NOT the Gmail password)
    # host = "smtp.gmail.com"                # optional, these are the Gmail defaults
    # port = 465

Without that section ``configured()`` is False and nothing is ever sent: the sign-in page then
offers Google sign-in and the saved recovery code instead of email codes.
"""
from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

from src.security import esc

BRAND = "Credit Desk"
TEAL, INK, SOFT = "#0B6B62", "#1B2430", "#5B6676"


def settings() -> dict:
    cfg: dict = {}
    try:
        import streamlit as st
        cfg = dict(st.secrets.get("email", {}))
    except Exception:
        cfg = {}
    env = {"sender": "CREDIT_DESK_SMTP_SENDER", "password": "CREDIT_DESK_SMTP_PASSWORD",
           "host": "CREDIT_DESK_SMTP_HOST", "port": "CREDIT_DESK_SMTP_PORT"}
    for key, var in env.items():
        if os.environ.get(var):
            cfg[key] = os.environ[var]
    cfg.setdefault("host", "smtp.gmail.com")
    cfg.setdefault("port", 465)
    return cfg


def configured() -> bool:
    cfg = settings()
    return bool(str(cfg.get("sender", "")).strip() and str(cfg.get("password", "")).strip())


def _html(title: str, intro: str, code: str, footer: str) -> str:
    digits = "".join(f'<span style="display:inline-block;width:38px;height:48px;line-height:48px;margin:0 3px;'
                     f'border-radius:8px;background:#E8F5F2;color:{TEAL};font-size:26px;font-weight:700;'
                     f'font-family:Consolas,monospace">{d}</span>' for d in code)
    return f"""<!doctype html><html><body style="margin:0;background:#F3F5F8;font-family:Segoe UI,Arial,sans-serif">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="padding:28px 12px">
<tr><td align="center"><table role="presentation" width="100%" style="max-width:480px;background:#fff;
border:1px solid #E1E6EC;border-radius:14px;overflow:hidden">
<tr><td style="background:{TEAL};padding:18px 26px;color:#fff;font-size:19px;font-weight:700">&#9703; {BRAND}</td></tr>
<tr><td style="padding:26px 26px 6px;color:{INK}"><div style="font-size:20px;font-weight:700;margin-bottom:10px">{esc(title)}</div>
<div style="font-size:15px;line-height:1.55;color:{SOFT}">{intro}</div></td></tr>
<tr><td align="center" style="padding:18px 26px">{digits}</td></tr>
<tr><td style="padding:0 26px 24px;font-size:13px;line-height:1.5;color:{SOFT}">{footer}</td></tr>
</table><div style="font-size:12px;color:#8A96A6;margin-top:14px">{BRAND} &middot; AUB Batch 10 &middot; Group 4
&middot; school project</div></td></tr></table></body></html>"""


def code_email(purpose: str, name: str, code: str, minutes: int) -> tuple[str, str, str]:
    """(subject, plain text, html) for a 6-digit code email."""
    who = esc(name or "there")
    if purpose == "reset":
        subject = f"{code} is your {BRAND} password reset code"
        title = "Reset your password"
        intro = f"Hello {who},<br>someone asked to reset the password of your {BRAND} account. Enter this code:"
        footer = (f"The code expires in {minutes} minutes and works once. If you did not ask for it, ignore this "
                  "email - your password stays the same. Never share this code; our staff will never ask for it.")
    else:
        subject = f"{code} is your {BRAND} verification code"
        title = "Confirm your email address"
        intro = f"Hello {who},<br>welcome to {BRAND}. Enter this code to confirm that this email address is yours:"
        footer = (f"The code expires in {minutes} minutes. If you did not create a {BRAND} account, ignore "
                  "this email.")
    text = (f"{title}\n\nYour {BRAND} code: {code}\n\nIt expires in {minutes} minutes and works once. "
            "If you did not ask for it, ignore this email.")
    return subject, text, _html(title, intro, code, footer)


def send(to: str, subject: str, text: str, html: str | None = None) -> None:
    """Send one email. Raises RuntimeError with a plain-language reason on failure."""
    cfg = settings()
    if not configured():
        raise RuntimeError("Email sending is not set up on this installation.")
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((BRAND, str(cfg["sender"]).strip()))
    msg["To"] = to
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    host, port = str(cfg["host"]), int(cfg["port"])
    password = str(cfg["password"]).replace(" ", "")
    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, context=ssl.create_default_context(), timeout=20) as s:
                s.login(str(cfg["sender"]).strip(), password)
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=20) as s:
                s.starttls(context=ssl.create_default_context())
                s.login(str(cfg["sender"]).strip(), password)
                s.send_message(msg)
    except smtplib.SMTPAuthenticationError as exc:
        raise RuntimeError("The email account refused the sign-in. Check the App password in "
                           ".streamlit/secrets.toml.") from exc
    except (smtplib.SMTPException, OSError) as exc:
        raise RuntimeError(f"The email could not be sent ({exc.__class__.__name__}). "
                           "Check the internet connection and try again.") from exc


def send_code(to: str, purpose: str, name: str, code: str, minutes: int) -> None:
    subject, text, html = code_email(purpose, name, code, minutes)
    send(to, subject, text, html)
