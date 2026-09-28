# pyright: strict
"""Contract tests for resource golden fixtures."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeAlias, cast

import pytest
from jsonschema.exceptions import ValidationError
from pydantic import BaseModel

from maivn_contracts.resources import (
    validate_derived_artifact,
    validate_processing_state,
    validate_resource_policy,
)

FIXTURES_DIR = Path(__file__).resolve().parents[2] / 'fixtures'
ContractValidator: TypeAlias = Callable[[dict[str, Any]], BaseModel]


def _load_fixture(name: str) -> list[dict[str, Any]]:
    loaded = json.loads((FIXTURES_DIR / name).read_text(encoding='utf-8'))
    assert isinstance(loaded, list)
    return cast('list[dict[str, Any]]', loaded)


def _dump_like_fixture(model: BaseModel, fixture: dict[str, Any]) -> dict[str, Any]:
    dumped = model.model_dump(mode='json', exclude_none=True)
    return _restore_explicit_nulls(dumped, fixture)


def _restore_explicit_nulls(dumped: dict[str, Any], fixture: dict[str, Any]) -> dict[str, Any]:
    for key, value in fixture.items():
        if value is None:
            dumped[key] = None
        elif isinstance(value, dict) and isinstance(dumped.get(key), dict):
            nested_dump: dict[str, Any] = cast('dict[str, Any]', dumped[key])
            nested_fixture: dict[str, Any] = cast('dict[str, Any]', value)
            dumped[key] = _restore_explicit_nulls(nested_dump, nested_fixture)
        elif isinstance(value, list) and isinstance(dumped.get(key), list):
            nested_dump_list: list[Any] = cast('list[Any]', dumped[key])
            nested_fixture_list: list[Any] = cast('list[Any]', value)
            dumped[key] = _restore_explicit_nulls_in_list(
                nested_dump_list,
                nested_fixture_list,
            )
    return dumped


def _restore_explicit_nulls_in_list(dumped: list[Any], fixture: list[Any]) -> list[Any]:
    restored: list[Any] = []
    for dumped_item, fixture_item in zip(dumped, fixture, strict=True):
        if isinstance(dumped_item, dict) and isinstance(fixture_item, dict):
            restored.append(
                _restore_explicit_nulls(
                    cast('dict[str, Any]', dumped_item),
                    cast('dict[str, Any]', fixture_item),
                ),
            )
        else:
            restored.append(dumped_item)
    return restored


@pytest.mark.parametrize(
    ('fixture_name', 'expected_count', 'validator'),
    [
        ('valid_resource_policies.json', 4, validate_resource_policy),
        ('valid_processing_states.json', 3, validate_processing_state),
        ('valid_derived_artifacts.json', 3, validate_derived_artifact),
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
        assert _dump_like_fixture(validator(fixture), fixture) == fixture


@pytest.mark.parametrize(
    ('fixture_name', 'expected_count', 'validator'),
    [
        ('invalid_resource_policies.json', 2, validate_resource_policy),
        ('invalid_processing_states.json', 1, validate_processing_state),
        ('invalid_derived_artifacts.json', 3, validate_derived_artifact),
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
