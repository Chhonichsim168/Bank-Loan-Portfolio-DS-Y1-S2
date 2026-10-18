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
    with st.form(f"{key}_attach", clear_on_submit=True, border=True):
        kind = st.selectbox("Document type", documents.KINDS)
        up = st.file_uploader("File", type=["pdf", "png", "jpg", "jpeg"])
        go = st.form_submit_button("Attach")
    if go:
        if up is None:
            st.error("Choose a file first.")
        else:
            try:
                documents.attach(case_id, up.getvalue(), up.name, kind, user.username, user.role)
                st.success("Attached.")
                st.rerun()
            except (ValueError, audit.AuditError) as exc:
                st.error(str(exc))
