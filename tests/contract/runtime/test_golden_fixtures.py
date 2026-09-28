# pyright: strict
"""Contract tests for runtime golden fixtures."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeAlias, cast

import pytest
from jsonschema.exceptions import ValidationError
from pydantic import BaseModel

from maivn_contracts.runtime import (
    validate_command,
    validate_run_config,
    validate_run_state,
    validate_stream_part,
)

FIXTURES_DIR = Path(__file__).resolve().parents[2] / 'fixtures'
ContractValidator: TypeAlias = Callable[[dict[str, Any]], object]


def _load_fixture(name: str) -> list[dict[str, Any]]:
    loaded = json.loads((FIXTURES_DIR / name).read_text(encoding='utf-8'))
    assert isinstance(loaded, list)
    return cast('list[dict[str, Any]]', loaded)


def _dump_like_fixture(model: BaseModel, fixture: dict[str, Any]) -> dict[str, Any]:
    dumped = model.model_dump(mode='json', exclude_none=True)
    for defaulted_field in ('recursion_limit', 'durability'):
        if defaulted_field not in fixture:
            dumped.pop(defaulted_field, None)
    fixture_interrupt = fixture.get('interrupt')
    dumped_interrupt = dumped.get('interrupt')
    if isinstance(fixture_interrupt, dict) and isinstance(dumped_interrupt, dict):
        typed_fixture_interrupt = cast('dict[str, Any]', fixture_interrupt)
        typed_dumped_interrupt = cast('dict[str, Any]', dumped_interrupt)
        for defaulted_field in ('kind', 'prompt_source', 'question', 'response_schema'):
            if defaulted_field not in typed_fixture_interrupt:
                typed_dumped_interrupt.pop(defaulted_field, None)
    return dumped


@pytest.mark.parametrize(
    ('fixture_name', 'expected_count', 'validator'),
    [
        ('valid_run_configs.json', 2, validate_run_config),
        ('valid_commands.json', 3, validate_command),
        ('valid_stream_parts.json', 3, validate_stream_part),
        ('valid_run_states.json', 3, validate_run_state),
    ],
)
def test_valid_golden_fixtures_are_pinned(
    fixture_name: str,
    expected_count: int,
    validator: ContractValidator,
) -> None:
    """Pin valid golden fixture counts and model-to-schema roundtrips."""
    fixtures = _load_fixture(fixture_name)

    assert len(fixtures) == expected_count
    for fixture in fixtures:
        validated = validator(fixture)
        assert isinstance(validated, BaseModel)
        assert _dump_like_fixture(validated, fixture) == fixture


@pytest.mark.parametrize(
    ('fixture_name', 'expected_count', 'validator'),
    [
        ('invalid_run_configs.json', 2, validate_run_config),
        ('invalid_commands.json', 1, validate_command),
        ('invalid_stream_parts.json', 2, validate_stream_part),
        ('invalid_run_states.json', 2, validate_run_state),
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
