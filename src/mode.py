"""How this installation is run. Defaults: a sign-in page with simple accounts, no account lock.

    CREDIT_DESK_REQUIRE_LOGIN=0      no sign-in at all - opens straight into the app (one person)
    CREDIT_DESK_LOCKOUT=1            lock an account for 15 minutes after 5 wrong passwords
    CREDIT_DESK_STRONG_PASSWORDS=1   new passwords need 12+ characters and a mix of character types
    CREDIT_DESK_DEMO_USERS=0         on first start create one admin with a random one-time password
                                     instead of the simple accounts below
    CREDIT_DESK_SINGLE_OPERATOR=1    with sign-in on, let one person approve their own cases
    CREDIT_DESK_AUTO_LOGOUT=1        sign out after idle minutes by default (users can still toggle)

Simple accounts created on first start (when data/users.json does not exist yet):
    admin / admin123     risk / risk123     officer / officer123

Without sign-in there is only one person, so a second approver can never exist: the app then runs
in single-operator mode and you approve referrals and policy changes yourself.
"""
from __future__ import annotations

import os

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


def _env(name: str) -> str:
    return os.environ.get(name, "").strip().lower()


def login_required() -> bool:
    return _env("CREDIT_DESK_REQUIRE_LOGIN") not in _FALSE


def lockout_enabled() -> bool:
    return _env("CREDIT_DESK_LOCKOUT") in _TRUE


def strong_passwords() -> bool:
    return _env("CREDIT_DESK_STRONG_PASSWORDS") in _TRUE


def simple_accounts() -> bool:
    return _env("CREDIT_DESK_DEMO_USERS") not in _FALSE


def auto_logout_default() -> bool:
    """Automatic sign-out after idle minutes. OFF unless CREDIT_DESK_AUTO_LOGOUT=1; each user can
    switch it on or off for themselves with the toggle in the left rail."""
    return _env("CREDIT_DESK_AUTO_LOGOUT") in _TRUE


def single_operator() -> bool:
    return not login_required() or _env("CREDIT_DESK_SINGLE_OPERATOR") in _TRUE
