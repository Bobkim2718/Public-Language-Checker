from __future__ import annotations

import os
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
PACKAGE_DATA_DIR = ROOT_DIR / "data"


def user_data_dir() -> Path:
    base = Path(os.environ.get("APPDATA") or (Path.home() / ".local" / "share"))
    path = base / "PublicLanguageChecker"
    path.mkdir(parents=True, exist_ok=True)
    return path
