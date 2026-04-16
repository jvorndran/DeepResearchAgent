"""Filesystem paths resolved relative to the backend package root."""

from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
OUTPUT_BASE_DIR = BACKEND_DIR / "outputs"
