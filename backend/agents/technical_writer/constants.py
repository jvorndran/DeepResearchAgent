"""Paths for technical writer artifacts."""

from __future__ import annotations

import os
from pathlib import Path

_PKG_DIR = Path(__file__).resolve().parent
BACKEND_DIR = _PKG_DIR.parent.parent
OUTPUT_BASE_DIR = Path(os.getenv("OUTPUT_DIR", str(BACKEND_DIR / "outputs")))
TECHNICAL_WRITER_SKILLS_DIR = BACKEND_DIR / "skills" / "technical-writer"
