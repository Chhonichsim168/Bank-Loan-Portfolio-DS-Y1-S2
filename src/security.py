"""
security.py
===========
Small, dependency-free helpers shared by every page that touches untrusted input or
writes data out of the app.

* ``csv_safe``     - neutralise spreadsheet formula injection in exported CSVs.
* ``safe_filename``- strip anything from an uploaded file name that is not a plain name.
* ``esc``          - HTML-escape a value before it is placed in ``unsafe_allow_html`` markup.
"""

from __future__ import annotations

import html
import re

import pandas as pd

# A cell that starts with one of these is treated as a formula by Excel / LibreOffice / Sheets.
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r", "\n")


def _neutralise(value):
    if isinstance(value, str) and value.startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value


def csv_safe(df: pd.DataFrame) -> pd.DataFrame:
    """Copy of ``df`` where every text cell (and text column name) that could execute as a
    spreadsheet formula is prefixed with an apostrophe. Numeric columns are untouched, so a
    genuine negative number stays a number."""
    out = df.copy()
    out.columns = [_neutralise(str(c)) for c in out.columns]
    for col in out.columns:
        series = out[col]
        if (pd.api.types.is_object_dtype(series) or pd.api.types.is_string_dtype(series)
                or isinstance(series.dtype, pd.CategoricalDtype)):
            out[col] = series.astype(object).map(_neutralise)
    return out


def to_safe_csv(df: pd.DataFrame, **kwargs) -> bytes:
    """CSV bytes (UTF-8) of ``df`` after formula-injection hardening."""
    kwargs.setdefault("index", False)
    return csv_safe(df).to_csv(**kwargs).encode("utf-8")


def safe_filename(name: str, default: str = "upload.csv", max_len: int = 80) -> str:
    """A plain file name: no directories, no control characters, no leading dots."""
    base = re.split(r"[\\/]", str(name or ""))[-1]
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base).lstrip("._")
    return (base[:max_len] or default)


def esc(value) -> str:
    """HTML-escape any value for use inside markup rendered with unsafe_allow_html."""
    return html.escape("" if value is None else str(value), quote=True)
