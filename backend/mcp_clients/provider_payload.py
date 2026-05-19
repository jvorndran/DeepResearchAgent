"""Canonical provider payload serialization helpers."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_provider_payload_bytes(payload: Any) -> bytes:
    """Serialize a raw provider payload for deterministic content hashing."""

    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        default=str,
    ).encode("utf-8")


def provider_payload_sha256(payload: Any) -> str:
    return hashlib.sha256(canonical_provider_payload_bytes(payload)).hexdigest()
