"""One configurable directory for private persistent application state."""
import os
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("CREDIT_DESK_DATA_DIR", ROOT / "data")).expanduser().resolve()
