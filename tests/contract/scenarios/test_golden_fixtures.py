# pyright: strict
"""Contract tests for scenario and trigger golden fixtures."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeAlias, cast

import pytest
from jsonschema.exceptions import ValidationError
from pydantic import BaseModel

from maivn_contracts.events import load_event_schema
from maivn_contracts.scenarios import (
    load_trigger_fire_schema,
    load_trigger_invocation_schema,
    validate_scenario,
    validate_trigger,
    validate_trigger_fire,
    validate_trigger_invocation,
)

FIXTURES_DIR = Path(__file__).resolve().parents[2] / 'fixtures'
LINEAGE_FIELDS = frozenset(
    {'root_event_id', 'parent_session_id', 'parent_trigger_id', 'trigger_chain_depth'},
)
ContractValidator: TypeAlias = Callable[[dict[str, Any]], BaseModel]


def _load_fixture(name: str) -> list[dict[str, Any]]:
    loaded = json.loads((FIXTURES_DIR / name).read_text(encoding='utf-8'))
    assert isinstance(loaded, list)
    return cast('list[dict[str, Any]]', loaded)


@pytest.mark.parametrize(
    ('fixture_name', 'expected_count', 'validator'),
    [
        ('valid_triggers.json', 10, validate_trigger),
        ('valid_trigger_fires.json', 2, validate_trigger_fire),
        ('valid_trigger_invocations.json', 1, validate_trigger_invocation),
        ('valid_scenarios.json', 5, validate_scenario),
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
        ('invalid_triggers.json', 12, validate_trigger),
        ('invalid_trigger_fires.json', 2, validate_trigger_fire),
        ('invalid_trigger_invocations.json', 2, validate_trigger_invocation),
        ('invalid_scenarios.json', 10, validate_scenario),
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


def test_lineage_fields_match_canonical_event_schema() -> None:
    """Keep trigger lineage field names identical to the canonical Event contract."""
    event_schema = load_event_schema()
    event_lineage_fields = LINEAGE_FIELDS.intersection(event_schema['properties'])
    fire_lineage_fields = set(load_trigger_fire_schema()['$defs']['lineage']['properties'])
    invocation_lineage_fields = set(
        load_trigger_invocation_schema()['$defs']['lineage']['properties'],
    )

    assert event_lineage_fields == LINEAGE_FIELDS
    assert fire_lineage_fields == event_lineage_fields
    assert invocation_lineage_fields == event_lineage_fields
