"""Cross-plane PostgreSQL resource-mutation lock identity."""

from __future__ import annotations

import hashlib


def resource_mutation_lock_key(resource_id: str) -> int:
    """Map an opaque resource ID to the shared signed advisory-lock key space."""
    digest = hashlib.sha256(resource_id.encode('utf-8')).digest()
    return int.from_bytes(digest[:8], 'big', signed=True)


__all__ = ['resource_mutation_lock_key']
