# pyright: strict
"""Contract tests for deployed-agent registry golden fixtures."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeAlias, cast

import pytest
from jsonschema.exceptions import ValidationError
from pydantic import BaseModel

from maivn_contracts.agents import (
    validate_agent,
    validate_agent_version,
    validate_message_binding,
)

FIXTURES_DIR = Path(__file__).resolve().parents[2] / 'fixtures'
ContractValidator: TypeAlias = Callable[[dict[str, Any]], BaseModel]


def _load_fixture(name: str) -> list[dict[str, Any]]:
    loaded = json.loads((FIXTURES_DIR / name).read_text(encoding='utf-8'))
    assert isinstance(loaded, list)
    return cast('list[dict[str, Any]]', loaded)


@pytest.mark.parametrize(
    ('fixture_name', 'expected_count', 'validator'),
    [
        ('valid_agents.json', 1, validate_agent),
        ('valid_agent_versions.json', 4, validate_agent_version),
        ('valid_message_bindings.json', 2, validate_message_binding),
    ],
)
def test_valid_golden_fixtures_are_pinned(
    fixture_name: str,
    expected_count: int,
    validator: ContractValidator,
) -> None:
    """Pin valid golden fixture counts and wire compatibility."""
    fixtures = _load_fixture(fixture_name)

    assert len(fixtures) == expected_count
    for fixture in fixtures:
        assert validator(fixture).model_dump(mode='json', exclude_none=True) == fixture


@pytest.mark.parametrize(
    ('fixture_name', 'expected_count', 'validator'),
    [
        ('invalid_agents.json', 1, validate_agent),
        ('invalid_agent_versions.json', 10, validate_agent_version),
        ('invalid_message_bindings.json', 2, validate_message_binding),
    ],
)
def test_invalid_golden_fixtures_are_pinned(
    fixture_name: str,
    expected_count: int,
    validator: ContractValidator,
) -> None:
    """Pin invalid golden fixture counts and rejection behavior."""
    fixtures = _load_fixture(fixture_name)

    assert len(fixtures) == expected_count
    for fixture in fixtures:
        with pytest.raises(ValidationError):
            validator(fixture)
