"""Optional libraries: which ones are installed, and how to install the rest.

The core app needs only streamlit, pandas, numpy, scikit-learn, scipy and plotly. Four more
libraries power single features; when one is missing, that feature shows a message with the
exact command to fix it instead of crashing the whole page.
"""
from __future__ import annotations

import importlib.util
import sys

FEATURES = {
    "cryptography": "Encrypted backup and restore (Data and governance)",
    "reportlab": "PDF decision records and customer letters",
    "openpyxl": "Excel reports (Loan book)",
    "matplotlib": "Coloured shading in some tables",
}


def has(lib: str) -> bool:
    try:
        return importlib.util.find_spec(lib) is not None and sys.modules.get(lib, 0) is not None
    except (ImportError, ValueError):
        return False


def missing() -> list[str]:
    return [lib for lib in FEATURES if not has(lib)]


def install_command(libs: list[str] | None = None) -> str:
    libs = libs or missing()
    return "python -m pip install " + " ".join(libs)


class MissingLibrary(RuntimeError):
    def __init__(self, lib: str):
        super().__init__(f"This feature needs the '{lib}' library, which is not installed on this computer. "
                         f"Close the app and run:  {install_command([lib])}   (or run 'START Credit Desk' again, "
                         f"which installs it).")
        self.lib = lib
