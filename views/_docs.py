"""Shared widget: attach and download case documents (used by Score an application, the Decision
queue and the Loan book)."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from src import audit, auth, documents, ui


SAMPLE_DIR = Path(__file__).resolve().parent.parent / "data" / "sample_documents"
# One sample file per document type, covering every accepted format (PDF, PNG, JPG).
SAMPLES = {
    "Identity": ("sample_identity.jpg", "image/jpeg"),
    "Income proof": ("sample_income_proof.pdf", "application/pdf"),
    "Bank statement": ("sample_bank_statement.pdf", "application/pdf"),
    "Collateral / valuation": ("sample_collateral_valuation.png", "image/png"),
    "Contract": ("sample_contract.pdf", "application/pdf"),
    "Other": ("sample_other.pdf", "application/pdf"),
}


def _samples(key: str) -> None:
    """Download buttons for a sample file of every document type, to test attaching."""
    with st.expander("Sample documents for testing (download, then attach below)"):
        st.caption("Fictional files marked SAMPLE - not real records. One for each document type, "
                   "covering every accepted format: PDF, PNG and JPG.")
        cols = st.columns(3)
        for i, (kind, (fname, mime)) in enumerate(SAMPLES.items()):
            path = SAMPLE_DIR / fname
            with cols[i % 3]:
                if path.exists():
                    st.download_button(f"{kind} ({fname.rsplit('.', 1)[1].upper()})", path.read_bytes(),
                                       file_name=fname, mime=mime, key=f"{key}_sample_{i}",
                                       **ui.STRETCH)
                else:
                    st.caption(f"{kind}: sample file missing")


def render_documents(case_id: str, key: str) -> None:
    user = auth.current_user()
    ui.section("Supporting documents",
               "Stored only on this computer, hash-checked on download. PDF, PNG or JPG, up to 10 MB each.")
    _samples(key)
    files = documents.for_case(case_id)
    if files.empty:
        st.caption("No documents attached yet.")
    for r in files.itertuples():
        a, b = st.columns([4, 1])
        a.markdown(f"**{r.kind}** - {r.label} ({r.size / 1024:,.0f} KB) - {r.username}, {r.ts[:16]} UTC")
        try:
            data, label, mime = documents.read(int(r.id))
            b.download_button("Download", data, file_name=label, mime=mime, key=f"{key}_dl_{r.id}")
        except (ValueError, FileNotFoundError) as exc:
            b.error(str(exc))
    # Choose a file -> the document type is read from the file automatically -> Attach.
    # The user never picks the type by hand, so it cannot be mislabelled by mistake.
    n = st.session_state.get(f"{key}_upload_n", 0)          # bumped after each attach to clear the box
    with st.container(border=True):
        up = st.file_uploader("Choose a file (PDF, PNG or JPG, up to 10 MB)", type=["pdf", "png", "jpg", "jpeg"],
                              key=f"{key}_file_{n}")
        if up is None:
            st.caption("The document type (Identity, Income proof, Bank statement, Collateral / valuation, "
                       "Contract or Other) is detected from the file automatically.")
            return
        kind, why = documents.detect_kind(up.name, up.getvalue())
        st.markdown(
            f'<div style="background:#E7F4EE;border:1px solid #B7DFCB;border-radius:8px;padding:8px 12px;'
            f'margin:2px 0 8px 0;color:#14532D">Document type detected: <b>{kind}</b>'
            f'<span style="color:#3F6B55"> &middot; {why}</span></div>', unsafe_allow_html=True)
        if st.button(f"Attach as {kind}", key=f"{key}_attach_{n}", type="primary"):
            try:
                documents.attach(case_id, up.getvalue(), up.name, kind, user.username, user.role)
                st.session_state[f"{key}_upload_n"] = n + 1
                st.success("Attached.")
                st.rerun()
            except (ValueError, audit.AuditError) as exc:
                st.error(str(exc))
