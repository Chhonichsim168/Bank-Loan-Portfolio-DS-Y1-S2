"""Literal, case-insensitive searching of already authorized data frames."""
import pandas as pd


def filter_records(frame, query="", columns=(), status="All", date_column=None, dates=None):
    out = frame.copy()
    if out.empty:
        return out
    if status != "All" and "status" in out:
        out = out[out["status"] == status]
    text = str(query or "").strip()
    if text:
        match = pd.Series(False, index=out.index)
        for column in columns:
            if column in out:
                match |= out[column].fillna("").astype(str).str.contains(text, case=False, regex=False)
        out = out[match]
    if date_column and dates and len(dates) == 2:
        day = pd.to_datetime(out[date_column], utc=True, errors="coerce").dt.tz_convert("Asia/Phnom_Penh").dt.date
        out = out[(day >= dates[0]) & (day <= dates[1])]
    return out
