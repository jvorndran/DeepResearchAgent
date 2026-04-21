"""Paths and storage roots for the data-engineer package."""
import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
DATA_STORAGE_DIR = Path(os.getenv("DATA_STORAGE_DIR", str(BACKEND_DIR / "data")))
