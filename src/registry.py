"""
registry.py
===========
A minimal model registry: every trained model is saved under a deterministic version id
(hash of the training data, features, constraints and hyper-parameters) with a metadata
file and a SHA-256 of the artefact.

Why: previously the model was re-fitted in memory on every start and never saved, so a score
could not be reproduced later. Now a decision record carries ``model_version`` and that exact
model can be reloaded. The artefact hash is checked before loading, because a pickle from a
tampered file is code execution.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path

import joblib
import pandas as pd

from src.risk_model import ModelResult, model_version, train_model

logger = logging.getLogger("credit_desk.registry")
ROOT = Path(__file__).resolve().parent.parent


def model_dir() -> Path:
    return Path(os.environ.get("CREDIT_DESK_MODEL_DIR", ROOT / "data" / "models"))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_or_train(book: pd.DataFrame) -> ModelResult:
    """Return the registered model for this exact training data, training and saving it if new."""
    version = model_version(book)
    d = model_dir()
    art, meta = d / f"{version}.joblib", d / f"{version}.json"
    if art.exists() and meta.exists():
        try:
            if json.loads(meta.read_text())["sha256"] == _sha(art):
                return joblib.load(art)
            logger.error("Model artefact %s failed its integrity check; re-training.", art.name)
        except Exception:
            logger.exception("Could not load registered model %s; re-training.", version)
    result = train_model(book)
    try:
        d.mkdir(parents=True, exist_ok=True)
        joblib.dump(result, art)
        os.chmod(art, 0o600)
        meta.write_text(json.dumps({
            "version": result.model_version, "trained_at": result.trained_at,
            "train_rows": result.train_rows, "roc_auc": result.roc_auc, "brier": result.brier,
            "ece": result.ece, "sha256": _sha(art),
        }, indent=2))
    except Exception:
        logger.exception("Could not save model %s to the registry", version)
    return result


def list_models() -> pd.DataFrame:
    rows = []
    d = model_dir()
    if d.exists():
        for f in sorted(d.glob("*.json")):
            try:
                rows.append(json.loads(f.read_text()))
            except Exception:
                pass
    cols = ["version", "trained_at", "train_rows", "roc_auc", "brier", "ece"]
    df = pd.DataFrame(rows)
    return df[[c for c in cols if c in df.columns]] if len(df) else pd.DataFrame(columns=cols)
