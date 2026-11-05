"""
khqr.py
=======
Real KHQR payment codes (Cambodia's national QR standard, EMVCo based) and the Bakong Open API
payment check.

How it works
------------
1. ``.streamlit/secrets.toml`` holds the bank's own STATIC receive-money QR (``static_qr``) - the text
   inside the KHQR that ABA / ACLEDA / Wing shows under "Receive money". It already carries the
   Bakong account ID and the account numbers, so the money goes straight to that bank account.
2. ``build()`` turns it into a DYNAMIC QR for one payment: amount, currency, a bill reference and an
   expiry time are added and the CRC is recomputed. Nothing else is changed.
3. ``check(md5)`` asks the Bakong Open API whether a payment for exactly that QR was made, using the
   developer token from https://api-bakong.nbc.gov.kh (``token``). The API only answers requests from
   Cambodian internet addresses, so run Credit Desk on a computer in Cambodia for this step.

No third-party relay server is used: the token only ever goes to api-bakong.nbc.gov.kh.

    [bakong]
    static_qr = "000201010211..."      # from your bank app's receive-money KHQR
    currency = "USD"                   # USD or KHR
    token = "eyJ..."                   # Bakong Open API token (optional: without it staff confirm)
    test_amount = 0.01                 # optional: charge this instead of the real amount while testing
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request

API = "https://api-bakong.nbc.gov.kh/v1/check_transaction_by_md5"
CURRENCY_CODES = {"USD": "840", "KHR": "116"}


# ---- settings ------------------------------------------------------------------------------
def settings() -> dict:
    cfg: dict = {}
    try:
        import streamlit as st
        cfg = dict(st.secrets.get("bakong", {}))
    except Exception:
        cfg = {}
    for key in ("static_qr", "currency", "token", "test_amount"):
        env = os.environ.get(f"CREDIT_DESK_BAKONG_{key.upper()}")
        if env:
            cfg[key] = env
    cfg["currency"] = str(cfg.get("currency", "USD")).upper()
    return cfg


def configured() -> bool:
    """A real receive-money QR is set up (payments go to a real bank account)."""
    qr = str(settings().get("static_qr", "")).strip()
    return bool(qr) and valid(qr)


def can_check() -> bool:
    """The Bakong token is set, so payments can be confirmed automatically."""
    return configured() and bool(str(settings().get("token", "")).strip())


def test_amount() -> float | None:
    try:
        value = float(settings().get("test_amount", 0) or 0)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


# ---- EMV TLV + CRC ---------------------------------------------------------------------------
def crc16(data: str) -> str:
    """CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF) as 4 upper-case hex digits."""
    crc = 0xFFFF
    for byte in data.encode("utf-8"):
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else (crc << 1)
            crc &= 0xFFFF
    return f"{crc:04X}"


def parse(payload: str) -> list[tuple[str, str]]:
    out, i = [], 0
    while i < len(payload):
        tag, length = payload[i:i + 2], int(payload[i + 2:i + 4])
        out.append((tag, payload[i + 4:i + 4 + length]))
        i += 4 + length
    return out


def _tlv(tag: str, value: str) -> str:
    if len(value) > 99:
        raise ValueError(f"KHQR field {tag} is too long.")
    return f"{tag}{len(value):02d}{value}"


def valid(payload: str) -> bool:
    try:
        fields = parse(payload)
        return (payload.startswith("000201") and fields[-1][0] == "63"
                and crc16(payload[:-4]) == payload[-4:].upper())
    except (ValueError, IndexError):
        return False


def merchant_name(payload: str | None = None) -> str:
    payload = payload or str(settings().get("static_qr", ""))
    return dict(parse(payload)).get("59", "") if payload else ""


def build(amount: float, currency: str | None = None, bill: str = "", minutes: int = 15,
          template: str | None = None, now_ms: int | None = None) -> str:
    """Dynamic KHQR for one payment, made from the bank's static receive-money QR."""
    template = template or str(settings().get("static_qr", "")).strip()
    if not valid(template):
        raise ValueError("The receive-money QR in secrets.toml is missing or damaged.")
    currency = (currency or settings()["currency"]).upper()
    if currency not in CURRENCY_CODES:
        raise ValueError("Currency must be USD or KHR.")
    if not amount or amount <= 0:
        raise ValueError("The amount must be greater than zero.")
    value = f"{amount:.2f}" if currency == "USD" else str(int(round(amount)))
    now_ms = now_ms or int(time.time() * 1000)
    fields = {tag: val for tag, val in parse(template) if tag not in ("63", "54", "62", "99")}
    fields["01"] = "12"                                       # dynamic: valid for one payment
    fields["53"] = CURRENCY_CODES[currency]
    fields["54"] = value
    if bill:
        fields["62"] = _tlv("01", bill[:25])                  # bill number shown in the bank app
    fields["99"] = _tlv("00", str(now_ms)) + _tlv("01", str(now_ms + minutes * 60_000))
    body = "".join(_tlv(tag, fields[tag]) for tag in sorted(fields)) + "6304"
    return body + crc16(body)


def md5(qr: str) -> str:
    return hashlib.md5(qr.encode("utf-8")).hexdigest()


# ---- Bakong Open API -------------------------------------------------------------------------
def check(qr_md5: str, timeout: float = 8.0) -> tuple[str, dict | str | None]:
    """('paid', data) | ('unpaid', None) | ('error', message). Never raises."""
    token = str(settings().get("token", "")).strip()
    if not token:
        return "error", "No Bakong token is set up."
    req = urllib.request.Request(API, data=json.dumps({"md5": qr_md5}).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            return "error", ("Bakong refused the token (expired or wrong?), or this computer is not in Cambodia. "
                             "Renew the token at api-bakong.nbc.gov.kh.")
        return "error", f"Bakong answered with error {exc.code}."
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return "error", f"Cannot reach Bakong ({exc.__class__.__name__}). Check the internet connection."
    if body.get("responseCode") == 0 and body.get("data"):
        return "paid", body["data"]
    return "unpaid", None
