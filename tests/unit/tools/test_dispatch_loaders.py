# pyright: strict
"""Unit tests for external-tool dispatch and callback contracts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest
from jsonschema.exceptions import ValidationError

from maivn_contracts.tools import (
    ToolCallback,
    ToolDispatch,
    load_tool_callback_schema,
    load_tool_dispatch_schema,
    validate_tool_callback,
    validate_tool_dispatch,
)

FIXTURES_DIR = Path(__file__).resolve().parents[2] / 'fixtures'
FORBIDDEN_FIELDS = {
    'callable',
    'source',
    'module',
    'artifact',
    'image',
    'command',
    'pickle',
    'package',
    'secret',
}


def _load_fixture(name: str) -> list[dict[str, object]]:
    loaded = json.loads((FIXTURES_DIR / name).read_text(encoding='utf-8'))
    assert isinstance(loaded, list)
    return cast('list[dict[str, object]]', loaded)


def test_dispatch_and_callback_schemas_are_closed_v1_data_envelopes() -> None:
    """Expose only JSON data fields and the established ToolOutcome callback reference."""
    dispatch_schema = load_tool_dispatch_schema()
    callback_schema = load_tool_callback_schema()

    assert dispatch_schema['properties']['schema_version']['const'] == 1
    assert callback_schema['properties']['schema_version']['const'] == 1
    assert dispatch_schema['additionalProperties'] is False
    assert callback_schema['additionalProperties'] is False
    assert FORBIDDEN_FIELDS.isdisjoint(dispatch_schema['properties'])
    assert FORBIDDEN_FIELDS.isdisjoint(callback_schema['properties'])


def test_validators_accept_shared_dispatch_and_callback_golden_fixtures() -> None:
    """Accept shared cross-language dispatch fixtures."""
    for fixture in _load_fixture('valid_tool_dispatches.json'):
        validated = validate_tool_dispatch(fixture)
        assert isinstance(validated, ToolDispatch)
        assert validated.model_dump(mode='json', exclude_none=True) == fixture
    for fixture in _load_fixture('valid_tool_callbacks.json'):
        validated = validate_tool_callback(fixture)
        assert isinstance(validated, ToolCallback)
        assert validated.model_dump(mode='json', exclude_none=True) == fixture


@pytest.mark.parametrize(
    'fixture_name',
    ['invalid_tool_dispatches.json', 'invalid_tool_callbacks.json'],
)
def test_validators_reject_invalid_and_executable_field_fixtures(fixture_name: str) -> None:
    """Reject malformed payloads and every prohibited code or secret carrier."""
    validator = (
        validate_tool_dispatch
        if fixture_name == 'invalid_tool_dispatches.json'
        else validate_tool_callback
    )
    for fixture in _load_fixture(fixture_name):
        with pytest.raises(ValidationError):
            validator(fixture)
