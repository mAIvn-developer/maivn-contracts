"""Local watcher payloads carry bounded metadata and a stable signed identity."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from maivn_contracts.scenarios import LocalFileEvent


def payload(**changes: Any) -> dict[str, Any]:
    """Return a valid metadata-only filesystem event."""
    return {
        'event_id': '20000000-0000-4000-8000-000000000001',
        'watch_id': 'invoices',
        'operation': 'created',
        'observed_at': '2026-09-05T17:00:00Z',
        'relative_path': 'september/invoice.pdf',
        'size_bytes': 42,
        'mtime_ns': '1788627600000000123',
        **changes,
    }


def test_local_file_metadata_preserves_nanoseconds_and_body_identity() -> None:
    """JSON roundtrip does not turn nanosecond timestamps into floating-point numbers."""
    event = LocalFileEvent.model_validate(payload())
    wire = event.model_dump(mode='json')
    assert wire['mtime_ns'] == '1788627600000000123'
    assert LocalFileEvent.model_validate_json(event.model_dump_json()) == event
    assert set(wire) == set(payload())


@pytest.mark.parametrize(
    'changes',
    [
        {'event_id': 'unstable-id'},
        {'event_id': 1},
        {'watch_id': '../escape'},
        {'operation': 'deleted'},
        {'size_bytes': True},
        {'size_bytes': -1},
        {'size_bytes': 2**53},
        {'mtime_ns': 1788627600000000123},
        {'mtime_ns': '-1'},
        {'mtime_ns': '1' * 21},
        {'observed_at': 1788627600},
        {'observed_at': '2026-09-05T17:00:00'},
        {'relative_path': '/absolute/file'},
        {'relative_path': '../escape'},
        {'relative_path': 'safe/../escape'},
        {'relative_path': 'C:/Users/private.txt'},
        {'relative_path': 'safe\\private.txt'},
        {'relative_path': 'safe//file'},
        {'relative_path': './file'},
        {'relative_path': 'file\x00'},
        {'relative_path': 'file\ud800'},
        {'relative_path': 'a' * 1025},
        {'contents': 'DO_NOT_SEND_CONTENT'},
        {'absolute_path': 'C:/private'},
    ],
)
def test_invalid_or_content_bearing_payload_refuses(changes: dict[str, Any]) -> None:
    """The source contract refuses paths, contents and coercions before persistence."""
    with pytest.raises(ValidationError):
        LocalFileEvent.model_validate(payload(**changes))
