"""A dedicated administrator entry point for complete encrypted backups."""
from src import customer_portal as portal, ui
from views.governance import _backup


def render():
    portal.require_role("admin")
    ui.page_header("Backup and restore", "Protect accounts, profiles, photos, loans, payments, messages and documents.",
                   eyebrow="Administration")
    _backup()
