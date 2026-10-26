# pyright: strict
"""An attachment carries its bytes exactly one way."""

from __future__ import annotations

import base64
from typing import Any

import pytest
from pydantic import ValidationError

from maivn_contracts.messages.model import Attachment

STORAGE_REF = {'bucket': 'memory-resources', 'path': 'prj/resources/a.pdf', 'sha256': 'a' * 64}


def _attachment(**sources: object) -> dict[str, Any]:
    return {
        'attachment_id': 'att-1',
        'filename': 'a.pdf',
        'mime_type': 'application/pdf',
        'size_bytes': 3,
        'content_hash': 'b' * 64,
        **sources,
    }


def test_attachment_accepts_a_storage_reference_or_inline_bytes() -> None:
    """Either source alone is a complete attachment."""
    stored = Attachment.model_validate(_attachment(storage_ref=STORAGE_REF))
    inline = Attachment.model_validate(
        _attachment(inline_base64=base64.b64encode(b'abc').decode()),
    )
    assert stored.inline_base64 is None
    assert inline.storage_ref is None


@pytest.mark.parametrize(
    'sources',
    [{}, {'storage_ref': STORAGE_REF, 'inline_base64': base64.b64encode(b'abc').decode()}],
)
def test_attachment_refuses_no_source_or_two_sources(sources: dict[str, object]) -> None:
    """Zero or two byte sources are refused."""
    with pytest.raises(
        ValidationError,
        match='exactly one of storage_ref or inline_base64 must be set',
    ):
        Attachment.model_validate(_attachment(**sources))
