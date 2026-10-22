"""
_result.py
==========
The result window ("invoice / receipt") that opens after an important button.

A page that finishes an important action calls ``push(...)`` and then ``st.rerun()``; app.py calls
``render_pending()`` on the next run, which opens the result once as a pop-up window with:
  * a receipt laid out like an invoice (number, date and time, the key facts, an itemised table),
  * what happens next,
  * a PDF of the same slip (and any extra files, e.g. the customer letter).

Nothing here changes data: it only shows the result of an action that has already been saved.
On a Streamlit without pop-up windows the same content is shown at the top of the page instead.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from html import escape as esc

import pandas as pd
import streamlit as st

from src import reports
from src.data_pipeline import to_local

KEY = "_cd_result"
TONES = {"good": ("#E7F4EE", "#1F7A5C", "&#10004;"), "warn": ("#FEF4E6", "#B54708", "&#9888;"),
         "stop": ("#FDECEA", "#B42318", "&#10006;"), "info": ("#E8F1F8", "#1D5F8C", "&#8505;")}


def _now_local() -> str:
    return to_local(datetime.now(timezone.utc).isoformat())


def push(*, title: str, number: str, status: str, rows: list[tuple[str, str]], tone: str = "good",
         table: pd.DataFrame | None = None, table_title: str = "", next_steps: list[str] | None = None,
         note: str = "", pdf_title: str | None = None, file_stem: str | None = None,
         extra_files: list[tuple[str, bytes, str, str]] | None = None,
         signatures: tuple[str, ...] = ("Prepared by", "Customer / checked by")) -> None:
    """Queue a result window for the next run. ``rows`` = (label, value) pairs shown and printed.
    ``extra_files`` = (button label, bytes, file name, mime) offered beside the slip PDF."""
    issued = _now_local() + " (Phnom Penh)"
    pdf = None
    if reports.HAVE_PDF:
        try:
            pdf = reports.receipt_pdf(title=pdf_title or title, number=number, issued=issued, rows=rows,
                                      table=table, table_title=table_title, note=note, status=status,
                                      signatures=signatures)
        except Exception:                       # a slip that cannot be printed never blocks the result
            pdf = None
    st.session_state[KEY] = {
        "title": title, "number": number, "status": status, "tone": tone, "rows": rows, "issued": issued,
        "table": None if table is None else table.to_dict("split"), "table_title": table_title,
        "next_steps": next_steps or [], "note": note, "pdf": pdf,
        "file_stem": file_stem or number, "extra_files": extra_files or [],
    }
    _loading_screen(title)


def has_pending() -> bool:
    return KEY in st.session_state


def _ignore_kw() -> dict:
    """Downloading from the window should not close it (Streamlit 1.43+ supports on_click='ignore')."""
    try:
        major, minor = (int(x) for x in st.__version__.split(".")[:2])
        return {"on_click": "ignore"} if (major, minor) >= (1, 43) else {}
    except Exception:
        return {}


def receipt_html(r: dict) -> str:
    bg, fg, icon = TONES.get(r["tone"], TONES["info"])
    rows = "".join(
        f'<tr><td style="padding:6px 10px;color:#5B6879;border-bottom:1px solid #EEF1F4;width:42%">{esc(str(k))}</td>'
        f'<td style="padding:6px 10px;color:#1B2430;font-weight:600;border-bottom:1px solid #EEF1F4">{esc(str(v))}</td></tr>'
        for k, v in r["rows"])
    return (
        f'<div class="cd-receipt" style="border:1px solid #D5DCE3;border-radius:10px;overflow:hidden;background:#FFFFFF">'
        f'<div style="display:flex;justify-content:space-between;align-items:flex-start;padding:14px 16px;'
        f'border-bottom:2px solid #0B6B62;gap:12px;flex-wrap:wrap">'
        f'<div><div style="font-size:1.05rem;font-weight:700;color:#0B6B62">Credit Desk</div>'
        f'<div style="font-size:0.8rem;color:#5B6879">{esc(r["title"])}</div></div>'
        f'<div style="text-align:right;font-size:0.8rem;color:#5B6879">No. <b style="color:#1B2430">'
        f'{esc(r["number"])}</b><br>{esc(r["issued"])}</div></div>'
        f'<div style="background:{bg};color:{fg};padding:10px 16px;font-weight:700;font-size:0.95rem">'
        f'{icon}&nbsp; {esc(r["status"])}</div>'
        f'<table style="width:100%;border-collapse:collapse;font-size:0.88rem">{rows}</table></div>')


def _buttons(r: dict) -> None:
    files = ([("Download slip (PDF)", r["pdf"], f"{r['file_stem']}.pdf", "application/pdf")] if r["pdf"] else []) \
        + list(r["extra_files"])
    cols = st.columns([2.2] * len(files) + [1] + [max(1.0, 8 - 2.2 * len(files))])
    for i, (label, data, name, mime) in enumerate(files):
        cols[i].download_button(label, data, file_name=name, mime=mime, key=f"_res_dl_{i}_{r['number']}",
                                type="primary" if i == 0 else "secondary", **_ignore_kw())
    if cols[len(files)].button("Close", key=f"_res_close_{r['number']}"):
        st.rerun()
    if not files and not reports.HAVE_PDF:
        st.caption("PDF slips need the 'reportlab' library (the START file installs it).")


LOADING_HTML = """
<style>
@keyframes cdspin {{ to {{ transform: rotate(360deg); }} }}
@keyframes cdbar {{ from {{ width: 8%; }} to {{ width: 100%; }} }}
@keyframes cdfade {{ from {{ opacity: 0; }} to {{ opacity: 1; }} }}
</style>
<div style="position:fixed;inset:0;z-index:999990;background:rgba(15,46,42,0.45);display:flex;
            align-items:center;justify-content:center;animation:cdfade .15s ease-out">
  <div style="background:#FFFFFF;border-radius:14px;padding:26px 32px;width:360px;max-width:88vw;
              box-shadow:0 18px 50px rgba(0,0,0,0.25);text-align:center;font-family:inherit">
    <div style="width:42px;height:42px;margin:0 auto 14px auto;border-radius:50%;border:4px solid #D7E6E3;
                border-top-color:#0B6B62;animation:cdspin .8s linear infinite"></div>
    <div style="font-weight:700;font-size:1.05rem;color:#14302C">{title}</div>
    <div style="color:#5B6879;font-size:0.9rem;margin-top:4px">Saved. Preparing your receipt...</div>
    <div style="height:6px;background:#E4EFEC;border-radius:99px;margin-top:16px;overflow:hidden">
      <div style="height:6px;background:#0B6B62;border-radius:99px;animation:cdbar {secs}s ease-out forwards"></div>
    </div>
  </div>
</div>
"""
LOADING_SECONDS = 1.1


def _loading_screen(title: str) -> None:
    """A short full-screen 'Preparing your receipt' moment between the click and the receipt, so the
    user sees the button worked. Drawn by push() just before the page reloads into the receipt."""
    try:
        st.markdown(LOADING_HTML.format(title=esc(title), secs=LOADING_SECONDS), unsafe_allow_html=True)
        time.sleep(LOADING_SECONDS)
    except Exception:          # purely cosmetic - never let it block the save that already happened
        pass


def _body(r: dict) -> None:
    st.markdown(receipt_html(r), unsafe_allow_html=True)
    _buttons(r)                                   # right under the slip, never below a long table
    if r["next_steps"]:
        st.markdown("**What happens next**")
        st.markdown("\n".join(f"{i}. {s}" for i, s in enumerate(r["next_steps"], 1)))
    if r["table"]:
        t = pd.DataFrame(r["table"]["data"], columns=r["table"]["columns"])
        st.markdown(f"**{esc(r['table_title'] or 'Details')}**")
        st.dataframe(t, hide_index=True, height=min(38 + 35 * len(t), 300))
    if r["note"]:
        st.caption(r["note"])


def render_pending() -> None:
    """Open the queued result once. Called by app.py on every run."""
    r = st.session_state.pop(KEY, None)
    if not r:
        return
    dialog = getattr(st, "dialog", None) or getattr(st, "experimental_dialog", None)
    if dialog is None:
        with st.container(border=True):
            st.markdown(f"### {esc(r['title'])}")
            _body(r)
        return
    try:
        dialog(r["title"], width="large")(_body)(r)
    except TypeError:                                   # very old signature without width
        dialog(r["title"])(_body)(r)
