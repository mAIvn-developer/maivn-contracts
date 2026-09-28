# pyright: strict
"""Contract tests for tools golden fixtures."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeAlias, cast

import pytest
from jsonschema.exceptions import ValidationError

from maivn_contracts.tools import (
    ErrorToolOutcome,
    FunctionToolSpec,
    MCPToolSpec,
    OkToolOutcome,
    SystemToolSpec,
    ToolCall,
    validate_tool_call,
    validate_tool_outcome,
    validate_tool_spec,
)

FIXTURES_DIR = Path(__file__).resolve().parents[2] / 'fixtures'
ContractModel: TypeAlias = (
    FunctionToolSpec | MCPToolSpec | SystemToolSpec | ToolCall | OkToolOutcome | ErrorToolOutcome
)
ContractValidator: TypeAlias = Callable[[dict[str, Any]], ContractModel]


def _load_fixture(name: str) -> list[dict[str, Any]]:
    loaded = json.loads((FIXTURES_DIR / name).read_text(encoding='utf-8'))
    assert isinstance(loaded, list)
    return cast('list[dict[str, Any]]', loaded)


@pytest.mark.parametrize(
    ('fixture_name', 'expected_count', 'validator'),
    [
        ('valid_tool_specs.json', 4, validate_tool_spec),
        ('valid_tool_calls.json', 2, validate_tool_call),
        ('valid_tool_outcomes.json', 3, validate_tool_outcome),
    ],
)
def test_valid_golden_fixtures_are_pinned(
    fixture_name: str,
    expected_count: int,
    validator: ContractValidator,
) -> None:
    """Pin valid fixture counts and model-to-schema roundtrips."""
    fixtures = _load_fixture(fixture_name)

    assert len(fixtures) == expected_count
    for fixture in fixtures:
        assert validator(fixture).model_dump(mode='json', exclude_none=True) == fixture


@pytest.mark.parametrize(
    ('fixture_name', 'expected_count', 'validator'),
    [
        ('invalid_tool_specs.json', 4, validate_tool_spec),
        ('invalid_tool_calls.json', 3, validate_tool_call),
        ('invalid_tool_outcomes.json', 6, validate_tool_outcome),
    ],
)
def test_invalid_golden_fixtures_are_pinned(
    fixture_name: str,
    expected_count: int,
    validator: ContractValidator,
) -> None:
    """Pin invalid fixture counts and rejection behavior."""
    fixtures = _load_fixture(fixture_name)

    assert len(fixtures) == expected_count
    for fixture in fixtures:
        with pytest.raises(ValidationError):
            validator(fixture)
