"""Stable hashing helpers for JSON-compatible payloads."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def stable_json_hash(payload: Any) -> str:
    """Return a stable sha256 hash for JSON-compatible payloads.

    Args:
        payload: JSON-compatible payload.

    Returns:
        Hex-encoded SHA-256 hash prefixed with ``sha256:``.
    """
    raw = json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    ).encode()
    return f"sha256:{hashlib.sha256(raw).hexdigest()}"
