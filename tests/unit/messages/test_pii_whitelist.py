# pyright: strict
"""PII whitelist validation is complete at the wire boundary."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from maivn_contracts.messages import PIIWhitelistEntry


@pytest.mark.parametrize('pattern', ['.*', '['])
def test_pattern_must_be_safe_to_compile(pattern: str) -> None:
    """Reject unusable or trivially permissive patterns on wire intake."""
    with pytest.raises(ValidationError):
        PIIWhitelistEntry(
            pattern=pattern,
            justification='Public values approved by legal.',
        )


def test_entity_type_is_normalized_at_wire_intake() -> None:
    """Keep category matching stable across every whitelist consumer."""
    entry = PIIWhitelistEntry(
        entity_type='  DateTime  ',
        justification='Scheduling dates are application data.',
    )

    assert entry.entity_type == 'datetime'


@pytest.mark.parametrize(
    ('selector', 'justification'),
    [
        ({'value': '  x  '}, 'Public value approved by legal.'),
        ({'entity_type': 'url'}, '        '),
    ],
)
def test_lengths_are_checked_after_whitespace_is_removed(
    selector: dict[str, str],
    justification: str,
) -> None:
    """Whitespace cannot satisfy the value or audit-justification floors."""
    with pytest.raises(ValidationError):
        PIIWhitelistEntry(**selector, justification=justification)
