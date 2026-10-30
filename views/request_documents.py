"""Supporting files on customer requests, with staff review and private downloads."""
from src.customer_i18n import t
import inspect
import streamlit as st
from src import audit, customer_documents as customer_docs, documents
from src.data_pipeline import to_local
from views._customer_feedback import show_error

def render(request_id, status, staff=False):
    st.markdown('**Supporting documents**')
    notice = st.session_state.pop(f'_document_notice_{request_id}', None)
    if notice:
        st.success(notice)
    files = customer_docs.for_request(request_id)
    if files.empty:
        st.caption(t('No documents uploaded yet.'))
    else:
        for d in files.itertuples():
            st.write(f'{d.label} · {d.kind} · {d.status}')
            st.caption(t(f'Uploaded {to_local(d.ts)}'))
            if d.note:
                st.info(d.note)
            try:
                content, label, mime = customer_docs.download(request_id, int(d.id))
                st.download_button(t('Download document'), content, file_name=label, mime=mime, key=f'request_document_download_{d.id}_{staff}')
            except (ValueError, PermissionError, OSError, audit.AuditError) as exc:
                show_error(exc, 'open this document')
            if staff:
                with st.form(f'document_review_{d.id}'):
                    outcome = st.selectbox(t('Document review'), ['Accepted', 'Needs replacement'], key=f'doc_outcome_{d.id}', format_func=t)
                    note = st.text_area(t('Notes for the customer'), value=d.note, max_chars=2000, key=f'doc_note_{d.id}')
                    save = st.form_submit_button(t('Save document review'), key=f'document_review_submit_{d.id}')
                if save:
                    try:
                        customer_docs.review(request_id, int(d.id), outcome, note)
                        st.session_state[f'_document_notice_{request_id}'] = 'Document review saved.'
                        st.rerun()
                    except (ValueError, PermissionError, OSError, audit.AuditError) as exc:
                        show_error(exc, 'save the document review')
    if not staff and status == 'Pending review':
        with st.form(f'request_document_upload_{request_id}', clear_on_submit=True):
            kind = st.selectbox(t('Document type'), documents.KINDS, key=f'doc_kind_{request_id}')
            options = {'max_upload_size': 10} if 'max_upload_size' in inspect.signature(st.file_uploader).parameters else {}
            upload = st.file_uploader(t('Supporting document'), type=['pdf', 'jpg', 'jpeg', 'png'], key=f'request_file_{request_id}', **options)
            st.caption(t('PDF, JPG or PNG · maximum 10 MB. Only you and the loan team can access these files.'))
            submit = st.form_submit_button(t('Upload document'), key=f'document_upload_submit_{request_id}')
        if submit:
            if upload is None:
                st.error(t('Choose a supporting document before pressing Upload document.'))
            else:
                try:
                    customer_docs.attach(request_id, upload.getvalue(), upload.name, kind)
                    from views.customer_feedback import confirm_action
                    confirm_action('Document uploaded',request_id + ' · ' + t('Your document is saved and available to the loan team.'))
                    st.rerun()
                except (ValueError, PermissionError, OSError, audit.AuditError) as exc:
                    show_error(exc, 'upload the document')
