# pyright: strict
"""Unit tests for exact-version internal trigger launch envelopes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest
from jsonschema.exceptions import ValidationError

from maivn_contracts.scenarios import (
    TriggerLaunch,
    load_trigger_launch_schema,
    validate_trigger_launch,
)

_REPLY_SEQUENCE = 2

FIXTURES_DIR = Path(__file__).resolve().parents[2] / 'fixtures'


def _load_fixture(name: str) -> list[dict[str, object]]:
    loaded = json.loads((FIXTURES_DIR / name).read_text(encoding='utf-8'))
    assert isinstance(loaded, list)
    return cast('list[dict[str, object]]', loaded)


def test_trigger_launch_schema_requires_an_exact_immutable_snapshot() -> None:
    """Make latest structurally impossible on the authenticated internal launch wire."""
    schema = load_trigger_launch_schema()

    assert schema['properties']['schema_version']['const'] == 1
    assert schema['additionalProperties'] is False
    assert schema['properties']['agent_version']['type'] == 'integer'
    assert schema['properties']['agent_version']['minimum'] == 1
    assert schema['properties']['conversation']['$ref'] == '#/$defs/conversation'
    assert schema['$defs']['conversation']['required'] == ['conversation_id', 'sequence']
    assert schema['$defs']['conversation']['properties']['sequence']['minimum'] == 1


def test_validate_trigger_launch_accepts_shared_golden_fixture() -> None:
    """Accept a launch envelope carrying the complete immutable agent version."""
    for fixture in _load_fixture('valid_trigger_launches.json'):
        validated = validate_trigger_launch(fixture)
        assert isinstance(validated, TriggerLaunch)
        assert validated.model_dump(mode='json', exclude_none=True) == fixture


def test_validate_trigger_launch_rejects_latest_and_incomplete_snapshots() -> None:
    """Reject non-exact selectors and incomplete launch snapshots before data-plane use."""
    for fixture in _load_fixture('invalid_trigger_launches.json'):
        with pytest.raises(ValidationError):
            validate_trigger_launch(fixture)


def test_validate_trigger_launch_accepts_strict_conversation_context() -> None:
    """Carry database-owned conversation order on the signed launch envelope."""
    fixture = _load_fixture('valid_trigger_launches.json')[0]
    fixture['conversation'] = {
        'conversation_id': 'conv-00000000-0000-4000-8000-000000000001',
        'sequence': _REPLY_SEQUENCE,
    }

    validated = validate_trigger_launch(fixture)

    assert validated.conversation is not None
    assert validated.conversation.sequence == _REPLY_SEQUENCE


@pytest.mark.parametrize(
    'conversation',
    [
        {'conversation_id': '', 'sequence': 1},
        {'conversation_id': 'conv-1', 'sequence': 0},
        {'conversation_id': 'conv-1', 'sequence': 1, 'project_id': 'forged-project'},
    ],
)
def test_validate_trigger_launch_rejects_malformed_conversation_context(
    conversation: dict[str, object],
) -> None:
    """Reject invalid or tenant-selecting signed conversation metadata."""
    fixture = _load_fixture('valid_trigger_launches.json')[0]
    fixture['conversation'] = conversation

    with pytest.raises(ValidationError):
        validate_trigger_launch(fixture)
