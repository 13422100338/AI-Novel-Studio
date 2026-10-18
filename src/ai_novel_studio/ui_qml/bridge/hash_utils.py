"""Shared content-hash helpers for editor payloads (C1.1).

The WebEngine page computes a synchronous FNV-1a change fingerprint and a
real SHA-256 digest for selections; the Python side must recompute both so a
malformed or tampered payload is rejected before it reaches the facade.
"""

from __future__ import annotations

from hashlib import sha256 as _sha256


def sha256(text: str) -> str:
    """Return the hex SHA-256 of the UTF-8 encoded text."""
    return _sha256(text.encode("utf-8")).hexdigest()


def fnv1a_hash(text: str) -> str:
    """Reproduce the JS-side FNV-1a fingerprint used by the Phase 1 prototype."""
    hash_value = 0x811C9DC5
    for character in text:
        hash_value ^= ord(character)
        hash_value = (hash_value * 0x01000193) & 0xFFFFFFFF
    return f"fnv1a:{hash_value:08x}"
