# pyright: strict
"""Unit tests for message contract loaders and validation."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeAlias, cast

import pytest
from jsonschema.exceptions import ValidationError
from pydantic import BaseModel

from maivn_contracts.messages import (
    load_attachment_schema,
    load_message_schema,
    validate_attachment,
    validate_message,
)

FIXTURES_DIR = Path(__file__).resolve().parents[2] / 'fixtures'
ATTACHMENT_SOURCE_VARIANT_COUNT = 2
ContractValidator: TypeAlias = Callable[[dict[str, Any]], BaseModel]


def _load_fixture(name: str) -> list[dict[str, Any]]:
    loaded = json.loads((FIXTURES_DIR / name).read_text(encoding='utf-8'))
    assert isinstance(loaded, list)
    return cast('list[dict[str, Any]]', loaded)


def test_load_attachment_schema_exposes_real_entity_fields() -> None:
    """Expose the strict Attachment field set and source exclusivity."""
    schema = load_attachment_schema()

    assert schema['$schema'] == 'https://json-schema.org/draft/2020-12/schema'
    assert schema['additionalProperties'] is False
    assert set(schema['properties']) == {
        'attachment_id',
        'filename',
        'mime_type',
        'size_bytes',
        'storage_ref',
        'inline_base64',
        'content_hash',
        'resource_id',
    }
    assert set(schema['required']) == {
        'attachment_id',
        'filename',
        'mime_type',
        'size_bytes',
        'content_hash',
    }
    assert len(schema['oneOf']) == ATTACHMENT_SOURCE_VARIANT_COUNT


def test_load_message_schema_exposes_owned_message_fields() -> None:
    """Expose the owned Message field set with no framework type leakage."""
    schema = load_message_schema()

    assert schema['$schema'] == 'https://json-schema.org/draft/2020-12/schema'
    assert schema['additionalProperties'] is False
    assert set(schema['properties']) == {
        'message_id',
        'role',
        'content',
        'attachments',
        'artifact_refs',
        'redaction',
        'metadata',
        'ts',
    }
    assert set(schema['required']) == {'message_id', 'role', 'content', 'ts'}
    assert set(schema['properties']['role']['enum']) == {
        'user',
        'assistant',
        'system',
        'tool',
    }
    assert 'langchain' not in json.dumps(schema).lower()
    assert schema['properties']['artifact_refs']['items'] == {
        '$ref': 'https://schemas.maivn.dev/artifacts/artifact_ref.schema.json'
    }


@pytest.mark.parametrize(
    ('fixture_name', 'validator'),
    [
        ('valid_attachments.json', validate_attachment),
        ('valid_messages.json', validate_message),
    ],
)
def test_validators_accept_valid_golden_fixtures(
    fixture_name: str,
    validator: ContractValidator,
) -> None:
    """Accept every valid message-contract fixture."""
    for fixture in _load_fixture(fixture_name):
        validated = validator(fixture)
        assert validated.model_dump(mode='json', exclude_none=True) == fixture


@pytest.mark.parametrize(
    ('fixture_name', 'validator'),
    [
        ('invalid_attachments.json', validate_attachment),
        ('invalid_messages.json', validate_message),
    ],
)
def test_validators_reject_invalid_golden_fixtures(
    fixture_name: str,
    validator: ContractValidator,
) -> None:
    """Reject every invalid message-contract fixture at the schema boundary."""
    for fixture in _load_fixture(fixture_name):
        with pytest.raises(ValidationError):
            validator(fixture)
