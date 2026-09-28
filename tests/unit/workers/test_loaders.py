# pyright: strict
"""Unit tests for worker connection and frame contracts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest
from jsonschema.exceptions import ValidationError

from maivn_contracts.workers import (
    WorkerConnection,
    WorkerFrame,
    load_worker_connection_schema,
    load_worker_frame_schema,
    validate_worker_connection,
    validate_worker_frame,
)

FIXTURES_DIR = Path(__file__).resolve().parents[2] / 'fixtures'


def _load_fixture(name: str) -> list[dict[str, object]]:
    loaded = json.loads((FIXTURES_DIR / name).read_text(encoding='utf-8'))
    assert isinstance(loaded, list)
    return cast('list[dict[str, object]]', loaded)


def test_worker_schemas_are_closed_v1_envelopes() -> None:
    """Expose closed v1 worker records and frames with extensions as the only open map."""
    connection_schema = load_worker_connection_schema()
    frame_schema = load_worker_frame_schema()

    assert connection_schema['properties']['schema_version']['const'] == 1
    assert connection_schema['additionalProperties'] is False
    assert frame_schema['additionalProperties'] is False
    assert frame_schema['properties']['protocol_version']['const'] == 1
    assert frame_schema['properties']['type']['enum'] == [
        'register',
        'registered',
        'heartbeat',
        'draining',
        'dispatch',
        'dispatch_ack',
        'tool_result',
        'error',
    ]


def test_validators_accept_shared_worker_golden_fixtures() -> None:
    """Accept shared cross-language worker fixtures."""
    for fixture in _load_fixture('valid_worker_connections.json'):
        validated = validate_worker_connection(fixture)
        assert isinstance(validated, WorkerConnection)
        assert validated.model_dump(mode='json', exclude_none=True) == fixture
    for fixture in _load_fixture('valid_worker_frames.json'):
        validated = validate_worker_frame(fixture)
        assert isinstance(validated, WorkerFrame)
        assert validated.model_dump(mode='json', exclude_none=True) == fixture


@pytest.mark.parametrize(
    'fixture_name',
    ['invalid_worker_connections.json', 'invalid_worker_frames.json'],
)
def test_validators_reject_invalid_shared_worker_golden_fixtures(fixture_name: str) -> None:
    """Reject malformed and executable-field worker payloads at the schema boundary."""
    validator = (
        validate_worker_connection
        if fixture_name == 'invalid_worker_connections.json'
        else validate_worker_frame
    )
    for fixture in _load_fixture(fixture_name):
        with pytest.raises(ValidationError):
            validator(fixture)
