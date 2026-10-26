"""Planning-choice contracts remain distinct from response model choices."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from maivn_contracts.agents import ModelSettings, PlanningChoice, load_agent_version_schema
from maivn_contracts.runtime import RunConfig, load_run_config_schema

if TYPE_CHECKING:
    from collections.abc import Callable


@pytest.mark.parametrize(
    'payload',
    [
        {},
        {'tier': 'advanced', 'model_id': 'gpt-5.6-terra'},
        {'tier': 'balanced'},
        {'model_id': ''},
    ],
)
def test_planning_choice_requires_one_valid_selector(payload: dict[str, str]) -> None:
    """Planning choices accept only one public planning tier or exact model id."""
    with pytest.raises(ValidationError):
        PlanningChoice.model_validate(payload)


def test_planning_choice_is_frozen_and_available_to_both_config_scopes() -> None:
    """Planning is a separate immutable selector on runs and stored agent versions."""
    planning = PlanningChoice(tier='deep')

    with pytest.raises(ValidationError):
        planning.tier = 'standard'

    settings = ModelSettings.model_validate(
        {'response': {'tier': 'balanced'}, 'planning': planning.model_dump(mode='json')}
    )
    run = RunConfig(user_id='usr-planning', thread_id='thr-planning', planning=planning)

    assert settings.planning == planning
    assert run.planning == planning


def test_run_config_schema_defines_a_distinct_planning_choice() -> None:
    """The authored runtime schema keeps planning tiers separate from response tiers."""
    schema = load_run_config_schema()

    assert schema['properties']['planning']['$ref'] == '#/$defs/planningChoice'
    assert schema['$defs']['planningChoice']['properties']['tier']['enum'] == [
        'auto',
        'standard',
        'advanced',
        'deep',
        None,
    ]


def test_agent_version_schema_defines_the_same_separate_planning_choice() -> None:
    """Stored immutable agent settings expose planning without changing response tiers."""
    schema = load_agent_version_schema()

    assert schema['$defs']['modelSettings']['properties']['planning'] == {
        '$ref': '#/$defs/planningChoice'
    }
    assert schema['$defs']['planningChoice']['properties']['tier']['enum'] == [
        'auto',
        'standard',
        'advanced',
        'deep',
        None,
    ]


def _planning_choice_schemas() -> dict[str, dict[str, Any]]:
    run_config = load_run_config_schema()
    agent_version = load_agent_version_schema()
    return {
        'run_config': {'$defs': run_config['$defs'], '$ref': '#/$defs/planningChoice'},
        'agent_version': {'$defs': agent_version['$defs'], '$ref': '#/$defs/planningChoice'},
        'model_json_schema': PlanningChoice.model_json_schema(),
    }


def _model_accepts(payload: dict[str, Any]) -> bool:
    try:
        PlanningChoice.model_validate(payload)
    except ValidationError:
        return False
    return True


@pytest.mark.parametrize(
    ('payload', 'accepted'),
    [
        ({'tier': 'deep', 'model_id': None}, True),
        ({'tier': 'deep'}, True),
        ({'model_id': 'gpt-5.6-terra'}, True),
        ({'tier': None, 'model_id': 'gpt-5.6-terra'}, True),
        ({}, False),
        ({'tier': None, 'model_id': None}, False),
        ({'tier': 'deep', 'model_id': ''}, False),
        ({'tier': 'deep', 'model_id': 'gpt-5.6-terra'}, False),
    ],
)
@pytest.mark.parametrize('schema_name', ['run_config', 'agent_version', 'model_json_schema'])
def test_planning_choice_schemas_agree_with_the_model(
    schema_name: str, payload: dict[str, Any], *, accepted: bool
) -> None:
    """Every published planning schema reaches the model's verdict, including a null selector."""
    validator = Draft202012Validator(_planning_choice_schemas()[schema_name])
    is_valid = cast('Callable[[object], bool]', validator.is_valid)

    assert _model_accepts(payload) is accepted
    assert is_valid(payload) is accepted
