# pyright: strict
"""Shared exact-byte HMAC vector tests for Mode A/B contracts."""

from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
from typing import cast

FIXTURES_DIR = Path(__file__).resolve().parents[1] / 'fixtures'


def test_mode_ab_hmac_vectors_sign_exact_body_bytes() -> None:
    """Keep Python interoperable with Go and TypeScript on exact request bytes."""
    loaded = json.loads(
        (FIXTURES_DIR / 'modes_ab_hmac_vectors.json').read_text(encoding='utf-8'),
    )
    assert isinstance(loaded, list)
    vectors = cast('list[dict[str, object]]', loaded)

    for vector in vectors:
        secret = cast('str', vector['secret'])
        timestamp = cast('int', vector['timestamp'])
        body = cast('str', vector['body'])
        signature = cast('str', vector['signature'])
        digest = hmac.new(
            secret.encode('utf-8'),
            f'{timestamp}.{body}'.encode(),
            hashlib.sha256,
        ).hexdigest()
        assert f't={timestamp},v1={digest}' == signature
